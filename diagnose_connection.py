"""
diagnose_connection.py - tests your Azure OpenAI connection end to end.

Run this any time something isn't working before touching main.py or
transcribe_videos.py - it isolates exactly which piece is broken and prints
the FULL underlying error (not the generic "Connection error." message).

Tests:
1. Config sanity (key/endpoint/deployment names are actually filled in)
2. A minimal TEXT call via the Responses API (matches your /openai/responses
   deployment) - this is what main.py needs to work.
3. A minimal AUDIO transcription call - this is what transcribe_videos.py
   needs. NOTE: this will likely fail with a 404/DeploymentNotFound unless
   your company has separately provisioned a Whisper deployment - your
   confirmed deployment (gpt-5.4-mini) is text-only. That specific failure
   is expected/informative, not a bug to chase.
"""

import sys
import traceback
from pathlib import Path

from openai import AzureOpenAI
import config

print("=" * 60)
print("STEP 0: Config check")
print("=" * 60)
API_KEY = getattr(config, "AZURE_OPENAI_API_KEY", "")
ENDPOINT = getattr(config, "AZURE_OPENAI_ENDPOINT", "")
API_VERSION = getattr(config, "AZURE_OPENAI_API_VERSION", "")
DEPLOYMENT = getattr(config, "AZURE_OPENAI_DEPLOYMENT", "")
WHISPER_DEPLOYMENT = getattr(config, "AZURE_OPENAI_WHISPER_DEPLOYMENT", "")

if not API_KEY or "PASTE-YOUR-AZURE-KEY-HERE" in API_KEY:
    print("ERROR: AZURE_OPENAI_API_KEY not set in config.py - fix this first.")
    sys.exit(1)
if not ENDPOINT:
    print("ERROR: AZURE_OPENAI_ENDPOINT not set in config.py - fix this first.")
    sys.exit(1)

print(f"API key found (starts with: {API_KEY[:7]}..., length: {len(API_KEY)})")
print(f"Endpoint: {ENDPOINT}")
print(f"API version: {API_VERSION}")
print(f"Text deployment: {DEPLOYMENT}")
print(f"Whisper deployment (for video transcription): {WHISPER_DEPLOYMENT}")

client = AzureOpenAI(api_key=API_KEY, azure_endpoint=ENDPOINT, api_version=API_VERSION)
print(f"Resolved base URL: {client.base_url}")

print()
print("=" * 60)
print("STEP 1: Minimal TEXT call via Responses API (what main.py needs)")
print("=" * 60)
try:
    response = client.responses.create(
        model=DEPLOYMENT,
        input="Say 'test ok' and nothing else.",
        max_output_tokens=20,
    )
    text = getattr(response, "output_text", None)
    print("SUCCESS. Response:", text if text else response)
except Exception as e:
    print(f"FAILED. Exception type: {type(e).__name__}")
    print(f"Exception message: {e}")
    print(f"Underlying cause (__cause__): {e.__cause__}")
    print("Full traceback:")
    traceback.print_exc()

print()
print("=" * 60)
print("STEP 2: Minimal AUDIO transcription (what transcribe_videos.py needs)")
print("=" * 60)
print("NOTE: this commonly fails with a 404 / DeploymentNotFound if your ")
print("Azure resource only has the text deployment provisioned, not a ")
print("separate Whisper deployment. That specific error means you need to ")
print("ask your Azure admin for a Whisper deployment - it does not mean ")
print("anything is broken with the text/main.py side.")
try:
    import wave
    import struct

    test_wav_path = Path("_diagnostic_test.wav")
    with wave.open(str(test_wav_path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        frames = b"".join(struct.pack("<h", int(100 * (i % 100))) for i in range(32000))
        wf.writeframes(frames)

    print(f"Created test file: {test_wav_path} ({test_wav_path.stat().st_size} bytes)")

    with open(test_wav_path, "rb") as f:
        result = client.audio.transcriptions.create(model=WHISPER_DEPLOYMENT, file=f)
    print("SUCCESS. Transcription result:", repr(result.text))
    test_wav_path.unlink(missing_ok=True)
except Exception as e:
    print(f"FAILED. Exception type: {type(e).__name__}")
    print(f"Exception message: {e}")
    print(f"Underlying cause (__cause__): {e.__cause__}")

print()
print("=" * 60)
print("Done. Paste this ENTIRE output back.")
print("=" * 60)
