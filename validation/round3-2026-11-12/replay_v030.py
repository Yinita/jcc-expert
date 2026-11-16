"""Consumed-development postprocessing replay over actual, unedited OCR output.

Only the whole-image OCR is reused. HUD fallback crops still run the local OCR.
This avoids re-reading all old screenshots after a shop postprocessing change;
it is not an independent test, model training or an end-to-end timing benchmark.
"""
import copy
import hashlib
import json
from pathlib import Path
from app.vision import ScreenshotRecognizer as ProductionRecognizer

CACHE=Path(__file__).with_name('development_ocr_cache.json')


class ScreenshotRecognizer(ProductionRecognizer):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self._replay=json.loads(CACHE.read_text())['by_file_sha256']
        self._current_replay=None

    def recognize(self,image_path,mode,layout_profile=None):
        if layout_profile is not None:
            raise ValueError('This consumed-development replay is default-only')
        self._current_replay=self._replay[hashlib.sha256(Path(image_path).read_bytes()).hexdigest()]
        return super().recognize(image_path,mode)

    def _ocr(self,image):
        entry=self._current_replay
        self._last_ocr_engine=entry['engine']+' / recorded whole-image OCR'
        return copy.deepcopy(entry['lines']),entry['error']
