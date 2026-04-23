#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-$PWD/venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "Python executable not found: $PYTHON_BIN"
  echo "Set PYTHON_BIN or create venv at venv/bin/python"
  exit 1
fi

"$PYTHON_BIN" -m PyInstaller \
  --noconfirm \
  --clean \
  --name DriveSafe \
  --onedir \
  --windowed \
  --paths "$PWD" \
  --add-data "config.yaml:." \
  --add-data "configs:configs" \
  --add-data "assets:assets" \
  --add-data "models:models" \
  --add-data "tools:tools" \
  --collect-all vosk \
  --collect-all ultralytics \
  --collect-all cv2 \
  main.py

mkdir -p dist/DriveSafe/recordings

echo "Build complete"
echo "Executable: dist/DriveSafe/DriveSafe"
echo "Run with: ./dist/DriveSafe/DriveSafe"
