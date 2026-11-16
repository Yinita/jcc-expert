"""Adapter contract tests; real-game evaluation is kept in separate datasets."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.ocr_backend import normalize_output, RapidOCRBackend, get_ocr_backend


class OCRBackendTests(unittest.TestCase):
    def test_normalizes_coordinates_and_retains_line_text(self):
        rows = normalize_output([[[-2, 10], [80, 10], [80, 30], [-2, 30]]], ["金币 50"], [.95], 100, 50)
        self.assertEqual(rows[0]["compact_text"], "金币50")
        self.assertEqual(rows[0]["bbox"], [0., .2, .8, .4])
        self.assertEqual(rows[0]["confidence"], .95)

    def test_empty_and_invalid_results_are_safe(self):
        self.assertEqual(normalize_output(None, None, None, 100, 100), [])
        self.assertEqual(normalize_output([[[float('nan'), 3]]], ['text'], [.9], 100, 100), [])
        self.assertEqual(RapidOCRBackend(sys.executable).read(None), ([], "rapidocr_invalid_bgr_image"))

    def test_absent_runtime_does_not_install_or_download(self):
        get_ocr_backend.cache_clear()
        with patch("app.ocr_backend.subprocess.run", side_effect=OSError("missing")):
            self.assertIsNone(get_ocr_backend())
        get_ocr_backend.cache_clear()


if __name__ == '__main__':
    unittest.main()
