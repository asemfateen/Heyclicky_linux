# HeyClicky Linux Port 🐧

HeyClicky Linux is a voice-driven, screen-aware AI assistant built natively for Linux environments. It runs as a lightweight background daemon that captures your active screen and microphone when you hold down a hardware hotkey, queries Claude 3.5 Sonnet for vision-aware reasoning, and streams natural spoken audio back to you almost instantly.

Unlike the macOS version, this port bypasses heavy app frameworks and sandboxed display protocols, leveraging native Linux command-line utilities and hardware-level keypress capturing for ultra-low latency.

---

## Features

- **Hardware-Level Push-To-Talk**: Intercepts `Caps Lock` presses and releases directly via `/dev/input/` (using `evdev`), providing true push-to-talk capability across Wayland (Hyprland, GNOME, KDE) and X11 out-of-the-box.
- **Adaptive Screen Grabbing**: Automatically detects the session type and uses native, silent screenshot tools (like `grim` on Wayland/wlroots or `maim` on X11) to capture your desktop in milliseconds.
- **Low-Latency Streaming Speech**: Streams text responses from Claude and feeds ElevenLabs TTS audio chunks directly to `mpv`'s input stream for instant real-time playback.
- **Sleek HUD Overlay**: Renders an animated, glowing neon-blue pointer cursor and custom tooltip speech bubble using GTK3 (`PyGObject`) and Cairo, which is 100% click-through.
- **AppImage Distribution**: Packaged as a single standalone executable binary.

---

## Architecture Diagram

```mermaid
graph TD
    User([User Holds Caps Lock]) -->|evdev Hardware Interception| Overlay[overlay.py GTK3 Daemon]
    Overlay -->|1. Run press action| Trigger[trigger.sh]
    Trigger -->|2. Grab Screenshot| Capture[capture.py grim/maim]
    Trigger -->|3. Record Mic| Record[pw-record PipeWire]
    
    User([User Releases Caps Lock]) -->|evdev Release Event| Overlay
    Overlay -->|4. Run release action| Trigger
    Trigger -->|5. Stop Recording| Record
    Trigger -->|6. Process Context| Brain[brain.py asyncio]
    
    Record -->|Ingest wav| Brain
    Capture -->|Ingest png| Brain
    
    Brain -->|7. Speech-to-Text| AssemblyAI[AssemblyAI API]
    Brain -->|8. Visual Reasoning| Claude[Claude 3.5 Sonnet]
    Brain -->|9. Text-to-Speech Stream| ElevenLabs[ElevenLabs Flash]
    Brain -->|10. Write Pointer coords| StateJSON["/tmp/heyclicky_state.json"]
    StateJSON -.->|11. Poll coords| GTKOverlay
    GTKOverlay -.->|12. Render neon pointer| User
```

---

## 🚀 Quick Start (Recommended)

### One-Line Zero-Touch Install
For an automated setup that checks system dependencies (FUSE, curl, mpv), downloads the 1.4MB AppImage, creates the local Python virtual environment, and provisions hotkey permissions, run:

```bash
curl -fsSL https://raw.githubusercontent.com/asemfateen/Heyclicky_linux/main/install.sh | bash
```

### Manual Install
If you prefer to run the packaged AppImage directly from your clone directory:

```bash
# 1. Make the AppImage executable
chmod +x HeyClicky-x86_64.AppImage

# 2. Run the integrated setup/installer (installs system dependencies, configures permissions)
./HeyClicky-x86_64.AppImage setup

# 3. Start the background monitoring daemon
./HeyClicky-x86_64.AppImage daemon &
```

To run HeyClicky automatically when your system starts:
- **For AppImage**: Add `/path/to/HeyClicky-x86_64.AppImage daemon &` to your desktop environment startup applications.
- **For Python script**: A desktop file is automatically generated at `~/.config/autostart/heyclicky-daemon.desktop` by the installer pointing to the virtual environment python interpreter.

---

## Development

If you make modifications to the Python or Bash scripts inside the `src/` directory, you can rebuild the AppImage using the compiler script:
```bash
chmod +x src/build_appimage.sh
./src/build_appimage.sh
```
This will compile your modifications and overwrite the `HeyClicky-x86_64.AppImage` binary in the root directory.
