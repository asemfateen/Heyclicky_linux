#!/usr/bin/env python3
import os
import sys
import re
import json
import base64
import subprocess
import time

# Set configuration paths
CONFIG_DIR = os.path.expanduser("~/.config/heyclicky")
ENV_FILE = os.path.join(CONFIG_DIR, "env.conf")
CREDENTIALS_FILE = os.path.join(CONFIG_DIR, "credentials.env")
uid = os.getuid()
STATE_FILE = f"/tmp/heyclicky_state_{uid}.json"

AUDIO_INPUT = f"/tmp/heyclicky_voice_{uid}.wav"
SCREENSHOT_INPUT = f"/tmp/heyclicky_screen_{uid}.png"
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
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Error writing state file: {e}", file=sys.stderr)

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

def transcribe_audio(assemblyai_key):
    """Transcribes audio using AssemblyAI REST API via curl."""
    # 1. Upload audio file
    print("Uploading audio to AssemblyAI...")
    upload_proc = subprocess.run([
        "curl", "-s",
        "-H", f"authorization: {assemblyai_key}",
        "--data-binary", f"@{AUDIO_INPUT}",
        "https://api.assemblyai.com/v2/upload"
    ], capture_output=True, text=True)
    
    if upload_proc.returncode != 0:
        raise Exception(f"Upload failed: {upload_proc.stderr}")
        
    try:
        upload_data = json.loads(upload_proc.stdout)
    except Exception:
        raise Exception(f"Failed to parse upload response: {upload_proc.stdout}")
        
    upload_url = upload_data.get("upload_url")
    if not upload_url:
        error_msg = upload_data.get("error", upload_proc.stdout)
        raise Exception(f"Upload did not return URL: {error_msg}")
        
    # 2. Start transcription
    print("Starting transcription process...")
    payload = {"audio_url": upload_url}
    transcribe_proc = subprocess.run([
        "curl", "-s",
        "-H", f"authorization: {assemblyai_key}",
        "-H", "content-type: application/json",
        "-d", json.dumps(payload),
        "https://api.assemblyai.com/v2/transcript"
    ], capture_output=True, text=True)
    
    if transcribe_proc.returncode != 0:
        raise Exception(f"Transcription start failed: {transcribe_proc.stderr}")
        
    try:
        transcribe_data = json.loads(transcribe_proc.stdout)
    except Exception:
        raise Exception(f"Failed to parse transcription response: {transcribe_proc.stdout}")
        
    transcript_id = transcribe_data.get("id")
    if not transcript_id:
        error_msg = transcribe_data.get("error", transcribe_proc.stdout)
        raise Exception(f"Transcription start did not return ID: {error_msg}")
        
    # 3. Poll status
    print(f"Polling transcription status for ID: {transcript_id}...")
    poll_url = f"https://api.assemblyai.com/v2/transcript/{transcript_id}"
    while True:
        poll_proc = subprocess.run([
            "curl", "-s",
            "-H", f"authorization: {assemblyai_key}",
            poll_url
        ], capture_output=True, text=True)
        
        if poll_proc.returncode != 0:
            raise Exception(f"Polling failed: {poll_proc.stderr}")
            
        try:
            poll_data = json.loads(poll_proc.stdout)
        except Exception:
            raise Exception(f"Failed to parse poll response: {poll_proc.stdout}")
            
        status = poll_data.get("status")
        if status == "completed":
            return poll_data.get("text", "")
        elif status == "error":
            raise Exception(f"AssemblyAI transcription error: {poll_data.get('error')}")
            
        time.sleep(0.5)

def get_llm_response(provider, credentials, transcript_text):
    """Queries the selected LLM provider with screen image and transcript text using curl."""
    content = []
    
    # Read screenshot base64 if it exists
    image_data = ""
    if os.path.exists(SCREENSHOT_INPUT):
        try:
            with open(SCREENSHOT_INPUT, "rb") as image_file:
                image_bytes = image_file.read()
                image_data = base64.b64encode(image_bytes).decode("utf-8")
        except Exception as e:
            print(f"Warning: Failed to read screenshot: {e}", file=sys.stderr)

    if provider == "anthropic":
        anthropic_key = credentials.get("ANTHROPIC_API_KEY")
        content = []
        if image_data:
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
        payload = {
            "model": "claude-3-5-sonnet-20241022",
            "max_tokens": 1024,
            "system": SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": content}
            ]
        }
        print("Querying Claude via Anthropic API...")
        proc = subprocess.run([
            "curl", "-s", "-X", "POST", "https://api.anthropic.com/v1/messages",
            "-H", f"x-api-key: {anthropic_key}",
            "-H", "anthropic-version: 2023-06-01",
            "-H", "content-type: application/json",
            "-d", json.dumps(payload)
        ], capture_output=True, text=True)
        
        if proc.returncode != 0:
            raise Exception(f"Anthropic API request failed: {proc.stderr}")
        try:
            res_data = json.loads(proc.stdout)
        except Exception:
            raise Exception(f"Failed to parse Anthropic JSON response: {proc.stdout}")
            
        if "content" in res_data and len(res_data["content"]) > 0:
            return res_data["content"][0]["text"]
        else:
            error_msg = res_data.get("error", {}).get("message", proc.stdout)
            raise Exception(f"Anthropic API error: {error_msg}")

    elif provider == "openai":
        openai_key = credentials.get("OPENAI_API_KEY")
        content = [{"type": "text", "text": transcript_text}]
        if image_data:
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{image_data}"
                }
            })
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content}
            ],
            "max_tokens": 1024
        }
        print("Querying GPT-4o-mini via OpenAI API...")
        proc = subprocess.run([
            "curl", "-s", "-X", "POST", "https://api.openai.com/v1/chat/completions",
            "-H", "content-type: application/json",
            "-H", f"Authorization: Bearer {openai_key}",
            "-d", json.dumps(payload)
        ], capture_output=True, text=True)
        
        if proc.returncode != 0:
            raise Exception(f"OpenAI API request failed: {proc.stderr}")
        try:
            res_data = json.loads(proc.stdout)
        except Exception:
            raise Exception(f"Failed to parse OpenAI JSON response: {proc.stdout}")
            
        if "choices" in res_data and len(res_data["choices"]) > 0:
            return res_data["choices"][0]["message"]["content"]
        else:
            error_msg = res_data.get("error", {}).get("message", proc.stdout)
            raise Exception(f"OpenAI API error: {error_msg}")

    elif provider == "gemini":
        gemini_key = credentials.get("GEMINI_API_KEY")
        parts = [{"text": transcript_text}]
        if image_data:
            parts.append({
                "inlineData": {
                    "mimeType": "image/png",
                    "data": image_data
                }
            })
        payload = {
            "systemInstruction": {
                "parts": [{"text": SYSTEM_PROMPT}]
            },
            "contents": [
                {"parts": parts}
            ]
        }
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
        print("Querying Gemini-1.5-Flash via Google API...")
        proc = subprocess.run([
            "curl", "-s", "-X", "POST", url,
            "-H", "content-type: application/json",
            "-d", json.dumps(payload)
        ], capture_output=True, text=True)
        
        if proc.returncode != 0:
            raise Exception(f"Gemini API request failed: {proc.stderr}")
        try:
            res_data = json.loads(proc.stdout)
        except Exception:
            raise Exception(f"Failed to parse Gemini JSON response: {proc.stdout}")
            
        if "candidates" in res_data and len(res_data["candidates"]) > 0:
            parts = res_data["candidates"][0].get("content", {}).get("parts", [])
            if parts and "text" in parts[0]:
                return parts[0]["text"]
        
        error_msg = res_data.get("error", {}).get("message", proc.stdout)
        raise Exception(f"Gemini API error: {error_msg}")

    elif provider == "ollama":
        parts = [f"System instruction: {SYSTEM_PROMPT}", f"User question: {transcript_text}"]
        payload = {
            "model": "llava",
            "prompt": "\n\n".join(parts),
            "stream": False
        }
        if image_data:
            payload["images"] = [image_data]
            
        print("Querying local LLava model via Ollama API...")
        proc = subprocess.run([
            "curl", "-s", "-X", "POST", "http://localhost:11434/api/generate",
            "-H", "content-type: application/json",
            "-d", json.dumps(payload)
        ], capture_output=True, text=True)
        
        if proc.returncode != 0:
            raise Exception(f"Ollama API request failed: {proc.stderr}")
        try:
            res_data = json.loads(proc.stdout)
        except Exception:
            raise Exception(f"Failed to parse Ollama JSON response: {proc.stdout}")
            
        if "response" in res_data:
            return res_data["response"]
        else:
            raise Exception(f"Ollama response error: {proc.stdout}")
            
    else:
        raise Exception(f"Unsupported LLM provider: {provider}")

def stream_tts(elevenlabs_key, voice_id, text):
    """Streams text to ElevenLabs and plays it back using mpv via curl stdout -> mpv stdin pipe."""
    print("Initializing low-latency curl-to-mpv audio pipeline...")
    
    # 1. Start mpv process reading from standard input
    mpv_process = subprocess.Popen(
        ["mpv", "-", "--cache=no", "--no-buffer", "--terminal=no", "--demuxer-readahead-secs=0"],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    uid = os.getuid()
    mpv_pid_file = f"/tmp/heyclicky_mpv_{uid}.pid"
    try:
        with open(mpv_pid_file, "w") as f:
            f.write(str(mpv_process.pid))
    except Exception:
        pass

    payload = {
        "text": text,
        "model_id": "eleven_flash_v2_5",
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.75
        }
    }

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"

    # 2. Start curl in background, piping its output directly into mpv's input stream
    curl_process = subprocess.Popen([
        "curl", "-f", "-N", "-s", "-X", "POST", url,
        "-H", f"xi-api-key: {elevenlabs_key}",
        "-H", "Content-Type: application/json",
        "-H", "accept: audio/mpeg",
        "-d", json.dumps(payload)
    ], stdout=mpv_process.stdin)

    # 3. Wait for the processes to complete
    curl_process.wait()
    if mpv_process.stdin:
        mpv_process.stdin.close()
    mpv_process.wait()

    try:
        os.remove(mpv_pid_file)
    except OSError:
        pass

def main():
    uid = os.getuid()
    brain_pid_file = f"/tmp/heyclicky_brain_{uid}.pid"
    try:
        with open(brain_pid_file, "w") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass

    try:
        update_state("processing")
        
        # 1. Load keys and config
        credentials = load_env_variables(CREDENTIALS_FILE)
        
        anthropic_key = credentials.get("ANTHROPIC_API_KEY")
        openai_key = credentials.get("OPENAI_API_KEY")
        gemini_key = credentials.get("GEMINI_API_KEY")
        assemblyai_key = credentials.get("ASSEMBLYAI_API_KEY")
        elevenlabs_key = credentials.get("ELEVENLABS_API_KEY")
        voice_id = credentials.get("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE_ID

        provider = credentials.get("LLM_PROVIDER") or ""
        provider = provider.strip().lower()

        # Dynamic Auto-detection of provider
        if not provider:
            if anthropic_key:
                provider = "anthropic"
            elif openai_key:
                provider = "openai"
            elif gemini_key:
                provider = "gemini"
            else:
                provider = "ollama"

        print(f"Active LLM Switchboard Provider: {provider}")

        # Check required generic keys
        missing_keys = []
        if not assemblyai_key: missing_keys.append("ASSEMBLYAI_API_KEY")
        if not elevenlabs_key: missing_keys.append("ELEVENLABS_API_KEY")

        # Provider-specific key checks
        if provider == "anthropic" and not anthropic_key:
            missing_keys.append("ANTHROPIC_API_KEY")
        elif provider == "openai" and not openai_key:
            missing_keys.append("OPENAI_API_KEY")
        elif provider == "gemini" and not gemini_key:
            missing_keys.append("GEMINI_API_KEY")

        if missing_keys:
            print(f"Error: Missing configurations/keys in {CREDENTIALS_FILE}: {', '.join(missing_keys)}", file=sys.stderr)
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
            user_text = transcribe_audio(assemblyai_key)
            print(f"Transcript: {user_text}")
        except Exception as e:
            print(f"AssemblyAI Transcription failed: {e}", file=sys.stderr)
            update_state("idle")
            sys.exit(1)

        if not user_text.strip():
            print("No speech detected.")
            update_state("idle")
            sys.exit(0)

        # 4. Get LLM response
        print(f"Requesting response from LLM provider: {provider}...")
        try:
            llm_response = get_llm_response(provider, credentials, user_text)
            print(f"LLM Response: {llm_response}")
        except Exception as e:
            print(f"LLM API call failed ({provider}): {e}", file=sys.stderr)
            update_state("idle")
            sys.exit(1)

        # 5. Parse Pointing Tag
        point_pattern = r"\[POINT:(?:none|(\d+)\s*,\s*(\d+)(?::([^\]:\s][^\]:]*?))?(?::screen\d+)?)\]"
        match = re.search(point_pattern, llm_response)
        
        point_info = None
        clean_text = llm_response
        
        if match:
            clean_text = re.sub(point_pattern, "", llm_response).strip()
            if match.group(1) and match.group(2):
                point_info = {
                    "x": int(match.group(1)),
                    "y": int(match.group(2)),
                    "label": match.group(3).strip() if match.group(3) else "element"
                }

        update_state("responding", text=clean_text, point=point_info)

        # 6. Stream TTS
        print("Streaming TTS via ElevenLabs...")
        try:
            stream_tts(elevenlabs_key, voice_id, clean_text)
        except Exception as e:
            print(f"TTS streaming failed: {e}", file=sys.stderr)
        update_state("idle")
    finally:
        try:
            os.remove(brain_pid_file)
        except OSError:
            pass

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting...")
        update_state("idle")
