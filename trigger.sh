#!/bin/bash

# ==============================================================================
# HeyClicky Linux Port - Phase 3 Trigger Script
# ==============================================================================

PID_FILE="/tmp/clicky_record.pid"
AUDIO_OUT="/tmp/voice.wav"
SCREENSHOT_OUT="/tmp/screen.png"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Read environment variables
CONFIG_DIR="$HOME/.config/clicky"
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
        # Launch capture engine in background so voice recording starts instantly
        "$PYTHON_BIN" "$SCRIPT_DIR/capture.py" > /dev/null 2>&1 &

        echo "Recording audio..."
        # Start pw-record in background
        pw-record --rate=16000 --channels=1 --format=s16 "$AUDIO_OUT" > /dev/null 2>&1 &
        RECORD_PID=$!
        
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
