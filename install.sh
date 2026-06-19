#!/usr/bin/env bash
set -e

# Visual formatting
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== HeyClicky Linux Native Installer ===${NC}"

# 1. Standard Paths
CONFIG_DIR="$HOME/.config/heyclicky"
BIN_DIR="$HOME/.local/bin"
APPIMAGE_PATH="$BIN_DIR/HeyClicky-x86_64.AppImage"

echo -e "⚙️ Preparing local bin directory..."
mkdir -p "$BIN_DIR"

# Ensure ~/.local/bin is in the user's PATH or print a warning
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo -e "${YELLOW}Note: $BIN_DIR is not in your current PATH. You might need to add it to your shell config (.bashrc or .zshrc).${NC}"
fi

# 2. Distro-Specific FUSE and Dependency Check
echo -e "🔍 Inspecting system architecture and package managers..."
if [ -f /etc/debian_version ]; then
    echo -e "📦 Debian/Ubuntu platform detected."
    sudo apt update && sudo apt install -y libfuse2 curl mpv acl pulseaudio-utils jq
    # Install optional screenshot tools
    sudo apt install -y grim spectacle gnome-screenshot gir1.2-gtklayershell-0.1 || echo "Optional desktop utilities could not be fully installed. Bypassing..."
elif [ -f /etc/arch-release ]; then
    echo -e "📦 Arch Linux platform detected."
    sudo pacman -Sy --needed --noconfirm fuse2 curl mpv acl libpulse jq
    # Install optional screenshot/layer-shell tools
    sudo pacman -S --needed --noconfirm grim spectacle gnome-screenshot gtk-layer-shell || echo "Optional desktop utilities could not be fully installed. Bypassing..."
elif [ -f /etc/fedora-release ]; then
    echo -e "📦 Fedora platform detected."
    sudo dnf install -y fuse curl mpv acl pulseaudio-utils jq
    # Install optional screenshot/layer-shell tools
    sudo dnf install -y grim spectacle gnome-screenshot gtk-layer-shell || echo "Optional desktop utilities could not be fully installed. Bypassing..."
else
    echo -e "${YELLOW}⚠️ Unknown distro. Please ensure fuse2/libfuse2, curl, mpv, and acl are installed manually.${NC}"
fi

# 3. Download the AppImage Binary (1.4MB Client)
echo -e "📥 Downloading HeyClicky AppImage (Ultra-lean 1.4MB)..."
curl -fsSL -o "$APPIMAGE_PATH" "https://github.com/asemfateen/Heyclicky_linux/raw/main/HeyClicky-x86_64.AppImage"
chmod +x "$APPIMAGE_PATH"

# 4. Run the integrated AppImage setup to build the local virtual environment and config files
echo -e "⚙️ Initializing local user-space configs and Python virtual environment..."
"$APPIMAGE_PATH" setup

# 5. Hot-inject Live evdev Session Permissions & Persist via udev
echo -e "🔌 Binding permanent hardware group rules via udev..."
sudo usermod -aG input "$USER" || true

# Create a permanent udev rule for evdev event devices
echo 'KERNEL=="event*", SUBSYSTEM=="input", MODE="0640", GROUP="input"' | sudo tee /etc/udev/rules.d/99-heyclicky-input.rules > /dev/null

# Trigger and reload udev rules immediately without rebooting
sudo udevadm control --reload-rules && sudo udevadm trigger || true

# Apply temporary live ACL so it works instantly without a log-out/reboot
sudo setfacl -m u:"$USER":r /dev/input/event* || true

# 6. Success Output & Launch Directives
echo -e "\n${GREEN}✅ HeyClicky installation complete!${NC}"
echo -e "----------------------------------------"
echo -e "1. ${YELLOW}CRITICAL:${NC} Open ${BLUE}$CONFIG_DIR/credentials.env${NC} and add your real API keys."
echo -e "2. Start the desktop layer background daemon by running:"
echo -e "   ${BLUE}HeyClicky-x86_64.AppImage daemon &${NC}"
echo -e "----------------------------------------"
