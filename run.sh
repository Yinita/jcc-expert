#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
export OPENBLAS_NUM_THREADS="${JCC_BLAS_THREADS:-1}"
export OMP_NUM_THREADS="${JCC_BLAS_THREADS:-1}"
exec python3 -m uvicorn app.main:app --host "${JCC_HOST:-127.0.0.1}" --port "${JCC_PORT:-8765}"
