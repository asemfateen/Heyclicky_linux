#!/usr/bin/env python3
import os
import sys
import re
import json
import base64
import asyncio
import subprocess
import httpx

# Set configuration paths
CONFIG_DIR = os.path.expanduser("~/.config/clicky")
ENV_FILE = os.path.join(CONFIG_DIR, "env.conf")
CREDENTIALS_FILE = os.path.join(CONFIG_DIR, "credentials.env")
STATE_FILE = "/tmp/clicky_state.json"

AUDIO_INPUT = "/tmp/voice.wav"
SCREENSHOT_INPUT = "/tmp/screen.png"
DEFAULT_VOICE_ID = "kPzsL2i3teMYv0FxEYQ6"  # Rachel (default voice)

SYSTEM_PROMPT = (
    "You are a fast, casual AI assistant looking at the user's screen. The user will speak to you. "
    "Respond in 1-2 short, highly conversational sentences. Write for the ear, not the eye. "
    "NEVER use markdown, bullet points, or complex formatting. If you need to point to a specific "
    "UI element to help the user, include a tag at the very end of your response in this exact format: "
    "[POINT:x,y:label] where x and y are the coordinates of the element."
)

def update_state(state, text="", point=None):
    """Writes the current execution state to a JSON file for the UI overlay."""
    data = {
        "state": state,  # idle, processing, responding
        "text": text,
        "point": point   # {"x": int, "y": int, "label": str} or None
    }
    with open(STATE_FILE, "w") as f:
        json.dump(data, f)

def load_env_variables(file_path):
    """Loads variables from a shell-style .env file."""
    vars_dict = {}
    if not os.path.exists(file_path):
        return vars_dict
    with open(file_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, val = line.split("=", 1)
                vars_dict[key.strip()] = val.strip().strip('"').strip("'")
    return vars_dict

async def transcribe_audio(assemblyai_key):
    """Transcribes audio using AssemblyAI SDK."""
    import assemblyai as aai
    aai.settings.api_key = assemblyai_key
    
    # Run CPU/network-bound SDK transcription in a thread pool to avoid blocking the loop
    def run_transcription():
        transcriber = aai.Transcriber()
        return transcriber.transcribe(AUDIO_INPUT)
        
    loop = asyncio.get_running_loop()
    transcript = await loop.run_in_executor(None, run_transcription)
    
    if transcript.status == aai.TranscriptStatus.error:
        raise Exception(transcript.error)
    return transcript.text

async def get_claude_response(anthropic_key, transcript_text):
    """Queries Claude with screen image and transcript text."""
    from anthropic import AsyncAnthropic
    client = AsyncAnthropic(api_key=anthropic_key)

    content = []
    if os.path.exists(SCREENSHOT_INPUT):
        with open(SCREENSHOT_INPUT, "rb") as image_file:
            # Non-blocking file read helper can be run in executor if needed, but synchronous read is fine here
            image_bytes = image_file.read()
            image_data = base64.b64encode(image_bytes).decode("utf-8")
        
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": image_data
            }
        })

    content.append({
        "type": "text",
        "text": transcript_text
    })

    response = await client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": content}
        ]
    )
    return response.content[0].text

async def stream_tts(elevenlabs_key, voice_id, text):
    """Streams text to ElevenLabs and plays it back using mpv."""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
    headers = {
        "xi-api-key": elevenlabs_key,
        "Content-Type": "application/json",
        "accept": "audio/mpeg"
    }
    data = {
        "text": text,
        "model_id": "eleven_flash_v2_5",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75
        }
    }

    # Start mpv process reading from stdin
    mpv_process = subprocess.Popen(
        ["mpv", "--no-cache", "--no-terminal", "-"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    try:
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", url, json=data, headers=headers, timeout=60.0) as response:
                if response.status_code == 200:
                    async for chunk in response.aiter_bytes():
                        # Write audio chunk to mpv stdin
                        mpv_process.stdin.write(chunk)
                        mpv_process.stdin.flush()
                else:
                    error_text = await response.aread()
                    print(f"ElevenLabs TTS failed: Status code {response.status_code}, {error_text.decode()}", file=sys.stderr)
    except Exception as e:
        print(f"TTS Streaming failed: {e}", file=sys.stderr)
    finally:
        if mpv_process.stdin:
            mpv_process.stdin.close()
        # Wait for audio to finish playing in thread pool to avoid blocking async loop
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, mpv_process.wait)

async def main_async():
    update_state("processing")
    
    # 1. Load keys and config
    credentials = load_env_variables(CREDENTIALS_FILE)
    
    anthropic_key = credentials.get("ANTHROPIC_API_KEY")
    assemblyai_key = credentials.get("ASSEMBLYAI_API_KEY")
    elevenlabs_key = credentials.get("ELEVENLABS_API_KEY")
    voice_id = credentials.get("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE_ID

    missing_keys = []
    if not anthropic_key: missing_keys.append("ANTHROPIC_API_KEY")
    if not assemblyai_key: missing_keys.append("ASSEMBLYAI_API_KEY")
    if not elevenlabs_key: missing_keys.append("ELEVENLABS_API_KEY")

    if missing_keys:
        print(f"Error: Missing API keys in {CREDENTIALS_FILE}: {', '.join(missing_keys)}", file=sys.stderr)
        update_state("idle")
        sys.exit(1)

    # 2. Check input file
    if not os.path.exists(AUDIO_INPUT):
        print(f"Error: Audio input file {AUDIO_INPUT} not found.", file=sys.stderr)
        update_state("idle")
        sys.exit(1)

    # 3. Transcribe audio
    print("Transcribing audio...")
    try:
        user_text = await transcribe_audio(assemblyai_key)
        print(f"Transcript: {user_text}")
    except Exception as e:
        print(f"AssemblyAI Transcription failed: {e}", file=sys.stderr)
        update_state("idle")
        sys.exit(1)

    if not user_text.strip():
        print("No speech detected.")
        update_state("idle")
        sys.exit(0)

    # 4. Get Claude's response
    print("Calling Claude...")
    try:
        claude_response = await get_claude_response(anthropic_key, user_text)
        print(f"Claude Response: {claude_response}")
    except Exception as e:
        print(f"Anthropic Claude API call failed: {e}", file=sys.stderr)
        update_state("idle")
        sys.exit(1)

    # 5. Parse Pointing Tag
    point_pattern = r"\[POINT:(?:none|(\d+)\s*,\s*(\d+)(?::([^\]:\s][^\]:]*?))?(?::screen\d+)?)\]"
    match = re.search(point_pattern, claude_response)
    
    point_info = None
    clean_text = claude_response
    
    if match:
        clean_text = re.sub(point_pattern, "", claude_response).strip()
        if match.group(1) and match.group(2):
            point_info = {
                "x": int(match.group(1)),
                "y": int(match.group(2)),
                "label": match.group(3).strip() if match.group(3) else "element"
            }

    update_state("responding", text=clean_text, point=point_info)

    # 6. Stream TTS
    print("Streaming TTS via ElevenLabs...")
    await stream_tts(elevenlabs_key, voice_id, clean_text)
    update_state("idle")

def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\nExiting...")
        update_state("idle")

if __name__ == "__main__":
    main()
