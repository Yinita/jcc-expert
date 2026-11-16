import io,json,queue
from unittest.mock import patch
import numpy as np
from app.ocr_backend import RapidOCRBackend


class Process:
    def __init__(self):self.stdin=io.BytesIO();self.stdout=None;self.stderr=None
    def poll(self):return None
    def wait(self,timeout=None):return 0
    def kill(self):return None


def test_cache_returns_detached_data_and_does_not_resubmit_pixels():
    r=RapidOCRBackend('/unused');process=Process();responses=queue.Queue()
    responses.put(json.dumps({'lines':[{'text':'50','confidence':.99,'bbox':[.1,.2,.1,.1]}],'error':None}).encode())
    r._process=process;r._responses=responses
    image=np.zeros((100,200,3),dtype=np.uint8)
    lines,error=r.read(image);written=process.stdin.getvalue();assert error is None
    lines[0]['text']='mutated'
    again,error=r.read(image)
    assert again[0]['text']=='50' and process.stdin.getvalue()==written
    r.close()


def test_worker_timeout_fails_closed_and_is_reset():
    r=RapidOCRBackend('/unused');r._process=Process();r._responses=queue.Queue()
    with patch('app.ocr_backend.TIMEOUT_SECONDS',.001):
        rows,error=r.read(np.zeros((100,200,3),dtype=np.uint8))
    assert rows==[] and error=='rapidocr_timeout' and r._process is None
