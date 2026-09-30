#!/bin/sh
set -eu

mkdir -p "${PALEONIA_WORK_DIR:-/data}"

if [ -n "${DATABASE_URL:-}" ]; then
  python -m paleonia.db
fi

exec python -m paleonia --no-browser --host 0.0.0.0 --port "${PALEONIA_PORT:-8878}"
