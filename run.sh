#!/usr/bin/env bash
# run.sh – Launch DriveSafe
cd "$(dirname "$0")"

# Use explicit venv python (ensures we don't use global packages)
VENV_PYTHON="$PWD/venv/bin/python"

# Clear cv2's Qt plugin path (use system Qt, not cv2's)
unset QT_QPA_PLATFORM_PLUGIN_PATH

# Use the HDMI display
export DISPLAY=:1

# Run with venv python
exec "$VENV_PYTHON" main.py "$@"