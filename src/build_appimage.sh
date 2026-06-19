#!/bin/bash

# ==============================================================================
# HeyClicky Linux Port - AppImage Build Script
# ==============================================================================

set -e # Exit immediately on error

# Ensure execution context is in the script directory
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "Starting HeyClicky AppImage compilation..."

APP_DIR="HeyClicky.AppDir"
ICON_SOURCE="heyclicky.png"


# 1. Recreate clean directory structure
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/usr/bin"

# 2. Copy scripts into AppDir
echo "Copying source files..."
cp brain.py "$APP_DIR/usr/bin/"
cp overlay.py "$APP_DIR/usr/bin/"
cp capture.py "$APP_DIR/usr/bin/"
cp trigger.sh "$APP_DIR/usr/bin/"
cp setup.sh "$APP_DIR/usr/bin/"

# Ensure correct execution permissions inside the AppDir
chmod +x "$APP_DIR/usr/bin/"*

# 3. Create the AppRun entrypoint router script
echo "Generating AppRun entrypoint..."
cat << 'EOF' > "$APP_DIR/AppRun"
#!/bin/bash
# AppRun entrypoint script for HeyClicky AppImage

# Determine the absolute directory where AppRun is located
HERE="$(dirname "$(readlink -f "${0}")")"

# Load local environment settings to acquire virtual environment path VENV_PATH
CONFIG_DIR="$HOME/.config/heyclicky"
if [ -f "$CONFIG_DIR/env.conf" ]; then
    source "$CONFIG_DIR/env.conf"
fi

# Fall back to default python3 if no local virtual environment is active
PYTHON_BIN="${VENV_PATH:-/usr}/bin/python3"

# Route execution based on parameter command
case "$1" in
    setup)
        exec bash "$HERE/usr/bin/setup.sh"
        ;;
    daemon)
        exec "$PYTHON_BIN" "$HERE/usr/bin/overlay.py"
        ;;
    press)
        exec /usr/bin/env VENV_PATH="$VENV_PATH" "$HERE/usr/bin/trigger.sh" press
        ;;
    release)
        exec /usr/bin/env VENV_PATH="$VENV_PATH" "$HERE/usr/bin/trigger.sh" release
        ;;
    *)
        echo "Usage: HeyClicky.AppImage [setup|daemon|press|release]"
        exit 1
        ;;
esac
EOF
chmod +x "$APP_DIR/AppRun"

# 4. Create Desktop entry file
echo "Generating heyclicky.desktop entry..."
cat << 'EOF' > "$APP_DIR/heyclicky.desktop"
[Desktop Entry]
Type=Application
Name=HeyClicky
Icon=heyclicky
Exec=AppRun
Categories=Utility;
Comment=Voice-driven screen-aware AI assistant
Terminal=false
EOF

# 5. Copy the generated application icon
if [ -f "$ICON_SOURCE" ]; then
    echo "Copying application icon..."
    cp "$ICON_SOURCE" "$APP_DIR/heyclicky.png"
else
    echo "Warning: Base icon not found at $ICON_SOURCE. Creating blank placeholder."
    touch "$APP_DIR/heyclicky.png"
fi

# 6. Download appimagetool and compile
echo "Acquiring appimagetool..."
if [ ! -f "appimagetool-x86_64.AppImage" ]; then
    wget -q --show-progress "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x appimagetool-x86_64.AppImage
fi

echo "Building final AppImage..."
# Run tool with ARCH specified to avoid execution platform detection errors
export ARCH=x86_64
./appimagetool-x86_64.AppImage "$APP_DIR" "../HeyClicky-x86_64.AppImage"

echo "=============================================================================="
echo "AppImage compiled successfully: ../HeyClicky-x86_64.AppImage"
echo "=============================================================================="
