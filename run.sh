#!/usr/bin/env bash
# run.sh – Launch DriveSafe
cd "$(dirname "$0")"
# Ensure a display is set (Jetson default is :1)
export DISPLAY="${DISPLAY:-:1}"
exec python main.py "$@"
