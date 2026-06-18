#!/bin/bash

# ==============================================================================
# HeyClicky Linux Port - Phase 1 Universal Installer
# ==============================================================================

set -e # Exit immediately if a command exits with a non-zero status

# Text Formatting Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # Reset color

echo -e "${BLUE}============ HeyClicky Linux Installer ============${NC}"

# ------------------------------------------------------------------------------
# 1. Environment Detection
# ------------------------------------------------------------------------------
SESSION_TYPE=$(echo "$XDG_SESSION_TYPE" | tr '[:upper:]' '[:lower:]')
DESKTOP=$(echo "$XDG_CURRENT_DESKTOP" | tr '[:upper:]' '[:lower:]')

# Fallback check if XDG_SESSION_TYPE is empty
if [ -z "$SESSION_TYPE" ]; then
    if [ -n "$WAYLAND_DISPLAY" ]; then
        SESSION_TYPE="wayland"
    else
        SESSION_TYPE="x11"
    fi
fi

echo -e "Display Protocol detected : ${GREEN}$SESSION_TYPE${NC}"
echo -e "Desktop Environment       : ${GREEN}$DESKTOP${NC}"

# ------------------------------------------------------------------------------
# 2. Package Manager Detection & Dependency Mapping
# ------------------------------------------------------------------------------
echo -e "\n${YELLOW}[1/3] Detecting system package manager...${NC}"

if command -v apt-get &> /dev/null; then
    PKG_MGR="sudo apt-get install -y"
    # Base dependencies including python3-venv and pipewire-bin (which contains pw-record)
    DEPS="python3 python3-pip python3-venv python3-gi python3-gi-cairo mpv pipewire-bin pipewire-audio-client-libraries acl"
    # Protocol specific
    if [ "$SESSION_TYPE" == "x11" ]; then
        DEPS="$DEPS maim xdotool xclip"
    else
        DEPS="$DEPS python3-pydbus gir1.2-xdgdesktopportal-1.0"
    fi
elif command -v dnf &> /dev/null; then
    PKG_MGR="sudo dnf install -y"
    DEPS="python3 python3-pip python3-gobject python3-cairo mpv pipewire-utils acl"
    if [ "$SESSION_TYPE" == "x11" ]; then
        DEPS="$DEPS maim xdotool xclip"
    else
        DEPS="$DEPS python3-pydbus"
    fi
elif command -v pacman &> /dev/null; then
    PKG_MGR="sudo pacman -S --noconfirm --needed"
    DEPS="python python-pip python-gobject python-cairo mpv pipewire acl"
    if [ "$SESSION_TYPE" == "x11" ]; then
        DEPS="$DEPS maim xdotool xclip"
    else
        DEPS="$DEPS python-pydbus"
    fi
elif command -v zypper &> /dev/null; then
    PKG_MGR="sudo zypper in -y"
    DEPS="python3 python3-pip python3-gobject python3-cairo mpv pipewire acl"
    if [ "$SESSION_TYPE" == "x11" ]; then
        DEPS="$DEPS maim xdotool xclip"
    else
        DEPS="$DEPS python3-pydbus"
    fi
else
    echo -e "${RED}Error: Unsupported package manager. Manual dependency installation required.${NC}"
    exit 1
fi

echo -e "Package Manager Found     : ${GREEN}${PKG_MGR%% *}${NC}"

# ------------------------------------------------------------------------------
# 3. System Dependency Installation
# ------------------------------------------------------------------------------
echo -e "\n${YELLOW}[2/3] Installing system dependencies (Requires Sudo)...${NC}"
echo -e "Running: $PKG_MGR $DEPS"
$PKG_MGR $DEPS

# Configure Input Device Permissions for evdev hotkeys
echo -e "\n${YELLOW}Configuring system input permissions for hotkeys...${NC}"
# 1. Add user to input group (permanent across reboots)
if ! groups "$USER" | grep -q "\binput\b"; then
    echo "Adding $USER to the 'input' group for persistent keyboard monitoring..."
    sudo usermod -aG input "$USER"
fi

# 2. Apply ACL for instant session access (no reboot/logout needed)
if command -v setfacl &> /dev/null; then
    echo "Instantly granting read access to /dev/input/event* for this session..."
    sudo setfacl -m u:"$USER":r /dev/input/event*
else
    echo -e "${RED}Warning: setfacl command not found. Instant input permissions could not be applied.${NC}"
fi

# ------------------------------------------------------------------------------
# 4. Configuration & Directory Layout Creation
# ------------------------------------------------------------------------------
echo -e "\n${YELLOW}[3/3] Setting up local application directories and configs...${NC}"

CONFIG_DIR="$HOME/.config/clicky"
SHARE_DIR="$HOME/.local/share/clicky"
AUTOSTART_DIR="$HOME/.config/autostart"

mkdir -p "$CONFIG_DIR"
mkdir -p "$SHARE_DIR"
mkdir -p "$AUTOSTART_DIR"

# Set up Python Virtual Environment with System Site Packages enabled
# This isolates dependencies while allowing imports of native system modules like GObject (gi)
VENV_DIR="$SHARE_DIR/venv"
echo -e "Creating Python virtual environment at ${GREEN}$VENV_DIR${NC}..."
python3 -m venv --system-site-packages "$VENV_DIR"

# Upgrade pip inside venv and install packages
echo -e "Installing Python libraries within the virtual environment..."
"$VENV_DIR/bin/pip" install --upgrade pip
"$VENV_DIR/bin/pip" install anthropic assemblyai elevenlabs sounddevice numpy opencv-python evdev --quiet

# Write env.conf
ENV_FILE="$CONFIG_DIR/env.conf"
cat << EOF > "$ENV_FILE"
# HeyClicky Linux Generated Environment Configurations
SESSION_TYPE="$SESSION_TYPE"
DESKTOP="$DESKTOP"
CAPTURE_METHOD="$([ "$SESSION_TYPE" == "wayland" ] && echo "dbus-screencast" || echo "maim")"
OVERLAY_METHOD="gtk-window"
VENV_PATH="$VENV_DIR"
EOF

# Create empty credentials file safely if it doesn't exist
CRED_FILE="$CONFIG_DIR/credentials.env"
if [ ! -f "$CRED_FILE" ]; then
    cat << EOF > "$CRED_FILE"
# HeyClicky API Keys Config
ANTHROPIC_API_KEY=""
ELEVENLABS_API_KEY=""
ASSEMBLYAI_API_KEY=""
EOF
fi

# Generate an Autostart Desktop Entry pointing explicitly to virtual environment python & absolute daemon path
# Note: Exec path must be absolute and does not expand shell variables ($HOME or ~) in standard desktop environments.
cat << EOF > "$AUTOSTART_DIR/clicky-daemon.desktop"
[Desktop Entry]
Type=Application
Name=HeyClicky Linux Daemon
Exec=$VENV_DIR/bin/python3 $CONFIG_DIR/daemon.py
X-GNOME-Autostart-enabled=true
X-KDE-autostart-after=panel
NoDisplay=true
EOF

echo -e "${GREEN}Configuration written to: $ENV_FILE${NC}"
echo -e "${GREEN}Credentials template created at: $CRED_FILE${NC}"
echo -e "${GREEN}Autostart file generated at: $AUTOSTART_DIR/clicky-daemon.desktop${NC}"

echo -e "\n${GREEN}============ Phase 1 Completed Successfully! ============${NC}"
echo -e "You can now safely transition to Phase 2 (The Capture Engine)."
