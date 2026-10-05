"""
test_native_audio.py - tests whether your EXISTING gpt-5.4-mini deployment
can accept audio directly as input (separate from the Whisper transcription
endpoint that returned DeploymentNotFound).

WHY THIS IS WORTH TRYING:
Some modern multimodal models accept audio as a native input type (alongside
text and images) through the same deployment - this is different from the
dedicated /audio/transcriptions (Whisper) endpoint that failed earlier. If
your gpt-5.4-mini deployment supports this, you get spoken-narration
understanding using ONLY infrastructure you already have - no new Azure
deployment, no IT ticket.

If this fails with an error like "invalid content type" or "unsupported
modality", that tells us definitively this deployment is text+vision only,
and audio really does require a separate Whisper (or audio-capable)
deployment - at that point there's no further "use only what I have" option
left to try.

USAGE:
    python test_native_audio.py "C:\\rcm_generator\\RCM Files\\4.Central Ops_Loan Cancellation.mp4"
"""

import sys
import base64
import subprocess
from pathlib import Path

from openai import AzureOpenAI
import config

FFMPEG_PATH = "ffmpeg"

API_KEY = getattr(config, "AZURE_OPENAI_API_KEY", "")
ENDPOINT = getattr(config, "AZURE_OPENAI_ENDPOINT", "")
API_VERSION = getattr(config, "AZURE_OPENAI_API_VERSION", "")
DEPLOYMENT = getattr(config, "AZURE_OPENAI_DEPLOYMENT", "")

client = AzureOpenAI(api_key=API_KEY, azure_endpoint=ENDPOINT, api_version=API_VERSION)


def extract_short_audio_sample(video_path: Path, out_path: Path, start_sec: int = 60, duration_sec: int = 30):
    """Pulls just a 30-second audio clip from partway through the video -
    small and fast, enough to test whether narration exists AND whether the
    model can process audio at all, without committing to a full video."""
    subprocess.run(
        [FFMPEG_PATH, "-y", "-ss", str(start_sec), "-i", str(video_path),
         "-t", str(duration_sec), "-vn", "-ar", "16000", "-ac", "1", "-b:a", "64k",
         str(out_path)],
        check=True, capture_output=True,
    )


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_native_audio.py <path to one video file>")
        sys.exit(1)

    video_path = Path(sys.argv[1])
    if not video_path.exists():
        print(f"ERROR: File not found: {video_path}")
        sys.exit(1)

    sample_path = Path("_native_audio_test_sample.wav")
    print(f"Extracting a 30-second audio sample from {video_path.name} (starting at 00:01:00)...")
    try:
        extract_short_audio_sample(video_path, sample_path)
    except subprocess.CalledProcessError as e:
        print(f"ffmpeg failed: {e.stderr.decode(errors='ignore')[:500]}")
        sys.exit(1)

    print(f"Sample size: {sample_path.stat().st_size} bytes")
    b64_audio = base64.b64encode(sample_path.read_bytes()).decode("utf-8")

    print(f"\nSending to deployment '{DEPLOYMENT}' as native audio input...")
    try:
        response = client.responses.create(
            model=DEPLOYMENT,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "Transcribe or describe what is being said in this audio clip, as literally as possible."},
                        {"type": "input_audio", "input_audio": {"data": b64_audio, "format": "wav"}},
                    ],
                }
            ],
            max_output_tokens=500,
        )
        text = getattr(response, "output_text", None)
        print("\n" + "=" * 60)
        print("SUCCESS - this deployment DOES accept native audio input!")
        print("=" * 60)
        print("Result:", text if text else response)
        print("\nThis means we can build audio understanding using ONLY your")
        print("existing deployment - no Whisper needed. Tell Claude this worked.")
    except Exception as e:
        print("\n" + "=" * 60)
        print("FAILED - this deployment does not support native audio input")
        print("=" * 60)
        print(f"Exception type: {type(e).__name__}")
        print(f"Exception message: {e}")
        print("\nThis confirms your gpt-5.4-mini deployment is text+vision only.")
        print("Audio understanding genuinely requires a separate audio-capable")
        print("deployment (Whisper or gpt-4o-audio/similar) - there's no further")
        print("'use only what I have' option for the AUDIO specifically, though")
        print("the frame-based vision approach remains fully available.")
    finally:
        sample_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
