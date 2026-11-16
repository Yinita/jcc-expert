"""Optional offline RapidOCR adapter, isolated from the application's NumPy.

Install rapidocr==3.10.0 and a Python-compatible onnxruntime in a dedicated
virtualenv, then set JCC_RAPIDOCR_PYTHON to that environment's Python executable.
The current wheel bundles the official small ONNX models. Inference explicitly
requires those local files and blocks sockets: screenshots are never uploaded
and inference never downloads a missing model. No visualization font is used.

The subprocess boundary prevents a separate OCR environment from replacing the
host application's OpenCV/NumPy. Missing runtimes return None so callers can
retain the existing Tesseract fallback.
"""
from __future__ import annotations

import contextlib
import atexit
import base64
import copy
import hashlib
import functools
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import queue
import threading
from collections import OrderedDict

MAX_IMAGE_PIXELS = 32_000_000
TIMEOUT_SECONDS = 35


def normalize_output(boxes, texts, scores, width, height):
    """Convert RapidOCR's quadrilaterals to bounded normalized line records."""
    lines = []
    if width <= 0 or height <= 0 or boxes is None or texts is None or scores is None:
        return lines
    for points, text, score in zip(boxes, texts, scores):
        try:
            text = str(text).strip()
            score = float(score)
            xy = [(float(point[0]), float(point[1])) for point in points]
            if not text or not xy or not math.isfinite(score) or not all(math.isfinite(v) for p in xy for v in p):
                continue
            x1 = max(0., min(width, min(p[0] for p in xy)))
            y1 = max(0., min(height, min(p[1] for p in xy)))
            x2 = max(0., min(width, max(p[0] for p in xy)))
            y2 = max(0., min(height, max(p[1] for p in xy)))
            if x2 <= x1 or y2 <= y1:
                continue
            lines.append({"text": text, "compact_text": "".join(text.split()),
                          "confidence": round(max(0., min(1., score)), 5),
                          "bbox": [x1/width, y1/height, (x2-x1)/width, (y2-y1)/height]})
        except (TypeError, ValueError, IndexError):
            continue
    return lines


class RapidOCRBackend:
    name = "rapidocr_onnx_cpu_offline"

    def __init__(self, python_executable):
        self.python_executable = str(python_executable)
        self._lock = threading.Lock()
        self._process = None
        self._responses = None
        self._cache = OrderedDict()
        atexit.register(self.close)

    def close(self):
        process, self._process = self._process, None
        self._responses = None
        if process is not None:
            try:
                if process.stdin:
                    process.stdin.close()
                process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
                process.wait(timeout=2)
            for pipe in [process.stdout, process.stderr]:
                if pipe:
                    pipe.close()

    def _start(self):
        self.close()
        env = os.environ.copy()
        env.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
                   NUMEXPR_NUM_THREADS="1", VECLIB_MAXIMUM_THREADS="1")
        process = subprocess.Popen([self.python_executable, str(Path(__file__).resolve()), "--server"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
        responses = queue.Queue()
        def consume():
            try:
                for line in process.stdout:
                    responses.put(line)
            except (OSError, ValueError):
                pass
            finally:
                responses.put(None)
        threading.Thread(target=consume, name="jcc-ocr-output", daemon=True).start()
        self._process, self._responses = process, responses
        ready = responses.get(timeout=TIMEOUT_SECONDS)
        if not ready or json.loads(ready).get("ready") is not True:
            raise RuntimeError("rapidocr_worker_not_ready")

    def read(self, image):
        # Imports use only the host's already installed cv2 and numpy here.
        import cv2
        if image is None or not hasattr(image, "shape") or len(image.shape) != 3 or image.shape[2] != 3:
            return [], "rapidocr_invalid_bgr_image"
        height, width = image.shape[:2]
        if min(width, height) < 8 or width * height > MAX_IMAGE_PIXELS:
            return [], "rapidocr_image_dimensions_outside_limit"
        ok, encoded = cv2.imencode(".png", image)
        if not ok or encoded.nbytes > 20 * 1024 * 1024:
            return [], "rapidocr_image_encoding_failed_or_too_large"
        raw = encoded.tobytes()
        cache_key = hashlib.sha256(raw).hexdigest()
        with self._lock:
            if cache_key in self._cache:
                self._cache.move_to_end(cache_key)
                return copy.deepcopy(self._cache[cache_key]), None
            try:
                if self._process is None or self._process.poll() is not None:
                    self._start()
                frame = json.dumps({"image":base64.b64encode(raw).decode("ascii")}).encode()+b"\n"
                self._process.stdin.write(frame)
                self._process.stdin.flush()
                line = self._responses.get(timeout=TIMEOUT_SECONDS)
                if not line:
                    raise RuntimeError("rapidocr_worker_closed")
                payload = json.loads(line)
                lines, error = payload.get("lines", []), payload.get("error")
                if not error:
                    self._cache[cache_key] = copy.deepcopy(lines)
                    while len(self._cache) > 16:
                        self._cache.popitem(last=False)
                return lines, error
            except queue.Empty:
                self.close()
                return [], "rapidocr_timeout"
            except (OSError, ValueError, UnicodeError, RuntimeError):
                self.close()
                return [], "rapidocr_runtime_unavailable_or_invalid_response"


@functools.lru_cache(maxsize=1)
def get_ocr_backend():
    """Return the first installed isolated RapidOCR runtime, or None.

    This probes imports only; it does not install packages or download assets.
    Call get_ocr_backend.cache_clear() after installing a runtime in a live app.
    """
    project = Path(__file__).resolve().parents[1]
    workspace = Path(__file__).resolve().parents[3]
    candidates = [os.environ.get("JCC_RAPIDOCR_PYTHON"), os.environ.get("JCC_OCR_PYTHON"), sys.executable,
                  str(project/"var/ocr-runtime/bin/python"), str(project/".venv/bin/python"),
                  str(workspace/"work/ocr_runtime/bin/python")]
    checked = set()
    probe = "import importlib.util,sys;sys.exit(0 if importlib.util.find_spec('rapidocr') and importlib.util.find_spec('onnxruntime') else 1)"
    for candidate in candidates:
        if not candidate or candidate in checked or not Path(candidate).is_file():
            continue
        checked.add(candidate)
        try:
            result = subprocess.run([candidate, "-c", probe], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=8, check=False)
            if result.returncode == 0:
                return RapidOCRBackend(candidate)
        except (OSError, subprocess.TimeoutExpired):
            continue
    return None


def _worker(server=False):
    # Set native thread limits before importing any array or inference library.
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[key] = "1"
    try:
        with contextlib.redirect_stdout(sys.stderr):
            import socket
            import cv2
            import numpy as np
            import rapidocr
            from rapidocr import RapidOCR
            cv2.setNumThreads(2)
            models = Path(rapidocr.__file__).resolve().parent / "models"
            paths = {"Det": models/"PP-OCRv6_det_small.onnx", "Cls": models/"ch_ppocr_mobile_v2.0_cls_mobile.onnx",
                     "Rec": models/"PP-OCRv6_rec_small.onnx"}
            if not all(p.is_file() for p in paths.values()):
                raise FileNotFoundError("Bundled official small models are missing; install the pinned current wheel")

            def no_network(*args, **kwargs):
                raise RuntimeError("Network access is disabled during screenshot OCR")
            socket.socket = no_network
            socket.create_connection = no_network
            params = {"EngineConfig.onnxruntime.intra_op_num_threads": 2,
                      "EngineConfig.onnxruntime.inter_op_num_threads": 1,
                      "EngineConfig.onnxruntime.use_cuda": False,
                      "Global.log_level": "error", "Global.max_side_len": 2400,
                      "Global.use_cls": False, "Det.limit_side_len": 1280, "Det.limit_type": "max"}
            params.update({f"{task}.model_path": str(p) for task, p in paths.items()})
            engine = RapidOCR(params=params)
        def infer(raw):
            if len(raw) > 20*1024*1024:
                raise ValueError("Encoded input exceeds limit")
            image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None or image.shape[0]*image.shape[1] > MAX_IMAGE_PIXELS:
                raise ValueError("Invalid or oversized image")
            with contextlib.redirect_stdout(sys.stderr):
                output = engine(image)
            lines = normalize_output(output.boxes, output.txts, output.scores, image.shape[1], image.shape[0])
            return {"lines":lines,"error":None}
        if not server:
            print(json.dumps(infer(sys.stdin.buffer.read(20*1024*1024+1)),ensure_ascii=False),flush=True)
            return
        print(json.dumps({"ready":True}),flush=True)
        while True:
            frame = sys.stdin.buffer.readline(28*1024*1024+1)
            if not frame:
                break
            try:
                if len(frame) > 28*1024*1024:
                    raise ValueError("Oversized request")
                raw = base64.b64decode(json.loads(frame)["image"],validate=True)
                payload = infer(raw)
            except Exception as exc:
                payload={"lines":[],"error":"rapidocr_"+type(exc).__name__}
            print(json.dumps(payload,ensure_ascii=False),flush=True)
    except Exception as exc:
        print(json.dumps({"lines": [], "error": "rapidocr_"+type(exc).__name__}, ensure_ascii=False))
        print(str(exc), file=sys.stderr)


if __name__ == "__main__" and ("--worker" in sys.argv or "--server" in sys.argv):
    _worker(server="--server" in sys.argv)
