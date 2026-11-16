#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
python3 -m venv var/ocr-runtime
var/ocr-runtime/bin/python -m pip install -r requirements-ocr.txt
var/ocr-runtime/bin/python -c 'import rapidocr, onnxruntime; print("Local OCR runtime installed.")'
