#!/usr/bin/env bash
set -euo pipefail

XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
INSTALL_DIR="$XDG_DATA_HOME/drivesafe"
APPS_DIR="$XDG_DATA_HOME/applications"
BIN_DIR="$HOME/.local/bin"
DESKTOP_FILE="$APPS_DIR/drivesafe.desktop"
CLI_LINK="$BIN_DIR/drivesafe"

rm -rf "$INSTALL_DIR"
rm -f "$DESKTOP_FILE"
rm -f "$CLI_LINK"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi

echo "DriveSafe local install removed."
