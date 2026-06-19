#!/bin/bash

# ==============================================================================
# HeyClicky Linux Port - Phase 3 Trigger Script
# ==============================================================================

CURRENT_UID=$(id -u)
PID_FILE="/tmp/heyclicky_record_${CURRENT_UID}.pid"
AUDIO_OUT="/tmp/heyclicky_voice_${CURRENT_UID}.wav"
SCREENSHOT_OUT="/tmp/heyclicky_screen_${CURRENT_UID}.png"
BRAIN_PID_FILE="/tmp/heyclicky_brain_${CURRENT_UID}.pid"
MPV_PID_FILE="/tmp/heyclicky_mpv_${CURRENT_UID}.pid"
STATE_FILE="/tmp/heyclicky_state_${CURRENT_UID}.json"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Read environment variables
CONFIG_DIR="$HOME/.config/heyclicky"
if [ -f "$CONFIG_DIR/env.conf" ]; then
    source "$CONFIG_DIR/env.conf"
fi

# Use virtual environment python if available
PYTHON_BIN="${VENV_PATH:-/usr}/bin/python3"

print_usage() {
    echo "Usage: $0 [press|release]"
    exit 1
}

# Ensure an action argument is passed
if [ -z "$1" ]; then
    print_usage
fi

ACTION=$(echo "$1" | tr '[:upper:]' '[:lower:]')

case "$ACTION" in
    press)
        # Kill any active brain.py process
        if [ -f "$BRAIN_PID_FILE" ]; then
            OLD_BRAIN_PID=$(cat "$BRAIN_PID_FILE")
            if kill -0 "$OLD_BRAIN_PID" 2>/dev/null; then
                echo "Stopping old AI brain (PID: $OLD_BRAIN_PID)..."
                kill -15 "$OLD_BRAIN_PID" 2>/dev/null || true
            fi
            rm -f "$BRAIN_PID_FILE"
        fi

        # Kill any active mpv playback spawned by the old brain
        if [ -f "$MPV_PID_FILE" ]; then
            OLD_MPV_PID=$(cat "$MPV_PID_FILE")
            if kill -0 "$OLD_MPV_PID" 2>/dev/null; then
                echo "Stopping old playback (PID: $OLD_MPV_PID)..."
                kill -15 "$OLD_MPV_PID" 2>/dev/null || true
            fi
            rm -f "$MPV_PID_FILE"
        fi

        # Clear any stale overlay state and set to listening (atomic write)
        echo '{"state": "listening", "text": "", "point": null}' > "${STATE_FILE}.tmp"
        mv "${STATE_FILE}.tmp" "$STATE_FILE"

        # Check if already recording to prevent duplicate processes
        if [ -f "$PID_FILE" ]; then
            OLD_PID=$(cat "$PID_FILE")
            if kill -0 "$OLD_PID" 2>/dev/null; then
                echo "Already recording (PID: $OLD_PID). Stopping old recording first."
                kill -2 "$OLD_PID" 2>/dev/null || true
                sleep 0.1
            fi
        fi

        # Remove old artifacts to avoid stale files if capture fails
        rm -f "$AUDIO_OUT" "$SCREENSHOT_OUT"

        echo "Starting screen capture..."
        # Launch capture engine, saving PID so release handler can wait for it
        "$PYTHON_BIN" "$SCRIPT_DIR/capture.py" > /dev/null 2>&1 &
        CAPTURE_PID=$!
        echo "$CAPTURE_PID" > /tmp/heyclicky_capture_${CURRENT_UID}.pid

        echo "Recording audio..."
        # Start pw-record (PipeWire) or fall back to parecord (PulseAudio)
        if command -v pw-record >/dev/null 2>&1; then
            echo "Recording audio using PipeWire (pw-record)..."
            pw-record --rate=16000 --channels=1 --format=s16 "$AUDIO_OUT" > /dev/null 2>&1 &
            RECORD_PID=$!
        elif command -v parecord >/dev/null 2>&1; then
            echo "Recording audio using PulseAudio (parecord)..."
            parecord --format=s16ne --rate=16000 --channels=1 "$AUDIO_OUT" > /dev/null 2>&1 &
            RECORD_PID=$!
        else
            echo "Error: Neither pw-record nor parecord was found in PATH." >&2
            exit 1
        fi
        
        # Save PID
        echo "$RECORD_PID" > "$PID_FILE"
        echo "Recording started with PID: $RECORD_PID"
        ;;

    release)
        if [ ! -f "$PID_FILE" ]; then
            echo "Error: No active recording session found."
            exit 1
        fi

        RECORD_PID=$(cat "$PID_FILE")
        rm -f "$PID_FILE"

        if kill -0 "$RECORD_PID" 2>/dev/null; then
            echo "Stopping audio recording (PID: $RECORD_PID)..."
            # Send SIGINT (Ctrl+C) so pw-record can finalize the WAV header cleanly
            kill -2 "$RECORD_PID"
            
            # Wait for process to exit
            while kill -0 "$RECORD_PID" 2>/dev/null; do
                sleep 0.05
            done
            echo "Audio recording saved to: $AUDIO_OUT"
        else
            echo "Recording process $RECORD_PID was not running."
        fi

        # Wait for screen capture to finish before launching AI Brain
        CAPTURE_PID_FILE="/tmp/heyclicky_capture_${CURRENT_UID}.pid"
        if [ -f "$CAPTURE_PID_FILE" ]; then
            CAPTURE_PID=$(cat "$CAPTURE_PID_FILE")
            rm -f "$CAPTURE_PID_FILE"
            if kill -0 "$CAPTURE_PID" 2>/dev/null; then
                echo "Waiting for screen capture (PID: $CAPTURE_PID) to complete..."
                wait "$CAPTURE_PID" 2>/dev/null || true
            fi
        fi

        # Write state atomically: temp file + rename to avoid partial reads by overlay
        echo '{"state": "processing", "text": "", "point": null}' > "${STATE_FILE}.tmp"
        mv "${STATE_FILE}.tmp" "$STATE_FILE"

        # Call AI Brain if daemon/script exists
        BRAIN_SCRIPT="$SCRIPT_DIR/brain.py"
        if [ -f "$BRAIN_SCRIPT" ]; then
            echo "Passing captured context to AI Brain..."
            "$PYTHON_BIN" "$BRAIN_SCRIPT" &
        else
            echo "AI Brain ($BRAIN_SCRIPT) not implemented yet. Ready to proceed to Phase 4!"
        fi
        ;;

    *)
        print_usage
        ;;
esac
