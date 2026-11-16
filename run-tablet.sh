#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
export OPENBLAS_NUM_THREADS="${JCC_BLAS_THREADS:-1}"
export OMP_NUM_THREADS="${JCC_BLAS_THREADS:-1}"
exec python3 scripts/tablet_server.py
