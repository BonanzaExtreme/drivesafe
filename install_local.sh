#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
DIST_DIR="$ROOT_DIR/dist/DriveSafe"
ICON_SRC="$ROOT_DIR/assets/drivesafe-icon.svg"

XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
INSTALL_DIR="$XDG_DATA_HOME/drivesafe"
APPS_DIR="$XDG_DATA_HOME/applications"
BIN_DIR="$HOME/.local/bin"
DESKTOP_FILE="$APPS_DIR/drivesafe.desktop"
LAUNCHER_SCRIPT="$INSTALL_DIR/run-drivesafe.sh"

if [[ ! -x "$DIST_DIR/DriveSafe" ]]; then
  echo "Executable not found at $DIST_DIR/DriveSafe"
  echo "Build first with: ./build_executable.sh"
  exit 1
fi

if [[ ! -f "$ICON_SRC" ]]; then
  echo "Icon not found at $ICON_SRC"
  exit 1
fi

mkdir -p "$INSTALL_DIR" "$APPS_DIR" "$BIN_DIR"

# Replace previous local install with the latest build output.
rm -rf "$INSTALL_DIR"/*
cp -a "$DIST_DIR"/. "$INSTALL_DIR"/
cp "$ICON_SRC" "$INSTALL_DIR/drivesafe-icon.svg"

cat > "$LAUNCHER_SCRIPT" <<EOF
#!/usr/bin/env bash
set -euo pipefail
unset QT_QPA_PLATFORM_PLUGIN_PATH
if [[ -z "\${DISPLAY:-}" ]]; then
  export DISPLAY=:1
fi
exec "$INSTALL_DIR/DriveSafe" "\$@"
EOF
chmod +x "$LAUNCHER_SCRIPT"

cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=DriveSafe
Comment=Pedestrian Safety Assistant
Exec=$LAUNCHER_SCRIPT
Icon=$INSTALL_DIR/drivesafe-icon.svg
Terminal=false
Categories=Utility;
StartupNotify=true
EOF
chmod +x "$DESKTOP_FILE"

ln -sf "$LAUNCHER_SCRIPT" "$BIN_DIR/drivesafe"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" >/dev/null 2>&1 || true
fi

echo "Installed DriveSafe locally."
echo "App menu entry: DriveSafe"
echo "CLI launcher: $BIN_DIR/drivesafe"
