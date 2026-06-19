# Project Overview: HeyClicky Linux Port
**Goal:** Build a voice-driven, screen-aware AI assistant for Linux that mimics the macOS "HeyClicky" app.
**Architecture Philosophy:** We are NOT building a monolithic compiled application (no Rust/Tauri). We are building a modular, script-based architecture using Bash and Python that acts as an abstraction layer over native Linux desktop environments. 

## The Core Constraints (CRITICAL)
1. **Wayland vs. X11 Fragmentation:** The app must dynamically detect the user's environment. We cannot hardcode wlroots, GNOME, or KDE specific tools globally.
2. **The "Silent Capture" Rule:** The app must be able to take screenshots without triggering recurring user permission popups. For standard Wayland, this requires establishing a persistent DBus ScreenCast session.
3. **No Flatpaks/Snaps:** This relies on deep system integration. It will be distributed as a Git repository with an intelligent setup script.

## The Tech Stack
* **Orchestration & Installation:** Bash (`setup.sh`, `trigger.sh`)
* **Core Logic & APIs:** Python 3
* **Screen Capture (X11):** `maim` via subprocess
* **Screen Capture (Wayland):** `pydbus` interacting with `org.freedesktop.portal.ScreenCast`
* **Audio Capture/Playback:** `PipeWire` (`pw-record`) and `mpv`
* **UI Overlay (The Blue Triangle):** `PyGObject` (GTK3/4) using `input_shape_combine_region` for a click-through transparent window.
* **AI Providers:** Claude (Vision/Reasoning), AssemblyAI (STT), ElevenLabs (TTS).

## Project Roadmap (Execute in Order)

### Phase 1: The Universal Installer (`setup.sh`)
* Must detect the package manager (`apt`, `dnf`, `pacman`, `zypper`).
* Must detect `$XDG_SESSION_TYPE` and `$XDG_CURRENT_DESKTOP`.
* Installs X11 tools (`maim`) or Wayland tools (`python3-pydbus`) dynamically.
* Writes the detected configuration to `~/.config/heyclicky/env.conf`.

### Phase 2: The Capture Engine (`capture.py` / `capture.sh`)
* Reads `env.conf`.
* If X11: Runs `maim` to save `/tmp/screen.png`.
* If Wayland: Establishes a DBus ScreenCast session, requests a restorable token, connects to the PipeWire node, and grabs a silent frame to `/tmp/screen.png`.

### Phase 3: The Trigger System
* A Bash script bound to a global system hotkey.
* **On Press:** Starts `pw-record` to record the microphone and fires the Capture Engine.
* **On Release:** Kills `pw-record` and passes the audio + image to the AI Brain.

### Phase 4: The AI Brain (`brain.py`)
* Python daemon that sends the audio to AssemblyAI.
* Sends the transcribed text + `/tmp/screen.png` to Claude.
* System Prompt: "You are a fast, conversational AI assistant. Respond in short, casual sentences for text-to-speech. Never output markdown."
* Sends Claude's response to ElevenLabs and plays the audio back via `mpv`.

### Phase 5: The UI Overlay (`overlay.py`)
* A full-screen, transparent GTK window.
* Ignores all mouse events (click-through).
* Receives X/Y coordinates from Claude and animates a floating cursor (blue triangle) to that point on the screen.
