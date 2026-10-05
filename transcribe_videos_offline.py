"""
transcribe_videos_offline.py - transcribes video narration using VOSK, a
fully offline/local speech-to-text engine. No Azure, no OpenAI API, no
internet needed once set up - runs entirely on this server's CPU.

WHY THIS EXISTS:
Your gpt-5.4-mini Azure deployment is confirmed text+vision only (tested
directly - it rejects audio input). Getting real audio transcription
otherwise requires a new Azure deployment (Whisper) that needs someone
else's action. This script is a genuine alternative that needs nothing
from anyone else - just files you download once and copy over, same as
you've already done for every pip package in this project.

HONEST TRADE-OFFS vs Whisper/GPT-quality transcription:
- Lower accuracy, especially with background noise, overlapping speakers,
  accents, or company/product-specific jargon (loan/finance terminology
  may come out garbled more often than a cloud model would get right).
- No punctuation/capitalization by default in the small model (readable,
  but flatter than a polished transcript).
- Good enough to catch the GIST of what was explained verbally, and to
  supplement the vision-frame descriptions with rationale/context - not
  good enough to be the sole source of truth for exact wording.
- If a Whisper deployment comes through later, that will be meaningfully
  better and should replace this for anything requiring precision.

SETUP (one-time, on your internet-connected machine):
1. pip install vosk
2. Download a model from https://alphacephei.com/vosk/models
   Recommended starting point: vosk-model-small-en-us-0.15 (~40MB, fast,
   decent for clear business speech). For better accuracy at the cost of
   size/speed: vosk-model-en-us-0.22 (~1.8GB).
3. Extract the downloaded .zip - you'll get a folder like
   vosk-model-small-en-us-0.15/ containing several files (am, conf, graph,
   etc). Copy that WHOLE FOLDER to the server, into this project directory
   (e.g. rcm_generator/vosk-model-small-en-us-0.15/).
4. On the server: pip install vosk (offline, via your usual
   pip-download-then-transfer workflow - vosk is a small package)
5. Set VOSK_MODEL_PATH below to match the folder name you copied over.

USAGE:
    python transcribe_videos_offline.py "C:\\rcm_generator\\RCM Files"
"""

import os
import sys
import json
import wave
import subprocess
from pathlib import Path

FFMPEG_PATH = "ffmpeg"
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".mov", ".avi"}

BASE_DIR = Path(__file__).parent
SOURCE_DOCS_DIR = BASE_DIR / "source_docs"
TEMP_AUDIO_DIR = BASE_DIR / "_temp_audio_offline"

# Set this to the exact folder name you copied over, e.g.
# "vosk-model-small-en-us-0.15" (relative to this script) or a full path.
VOSK_MODEL_PATH = "vosk-model-small-en-us-0.15"


def extract_wav(video_path: Path, out_path: Path):
    """Vosk needs 16kHz mono PCM WAV - same format as our other extraction."""
    subprocess.run(
        [FFMPEG_PATH, "-y", "-i", str(video_path),
         "-vn", "-ar", "16000", "-ac", "1", "-f", "wav",
         str(out_path)],
        check=True, capture_output=True,
    )


def transcribe_wav(model, wav_path: Path) -> str:
    from vosk import KaldiRecognizer

    wf = wave.open(str(wav_path), "rb")
    recognizer = KaldiRecognizer(model, wf.getframerate())
    recognizer.SetWords(True)

    results = []
    while True:
        data = wf.readframes(4000)
        if len(data) == 0:
            break
        if recognizer.AcceptWaveform(data):
            result = json.loads(recognizer.Result())
            if result.get("text"):
                results.append(result["text"])
    final = json.loads(recognizer.FinalResult())
    if final.get("text"):
        results.append(final["text"])

    return " ".join(results)


def process_video(model, video_path: Path):
    print(f"\n-> {video_path.name}")
    wav_path = TEMP_AUDIO_DIR / f"{video_path.stem}.wav"
    TEMP_AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    print("   Extracting audio...")
    try:
        extract_wav(video_path, wav_path)
    except subprocess.CalledProcessError as e:
        print(f"   [ERROR] ffmpeg failed: {e.stderr.decode(errors='ignore')[:500]}")
        return

    print("   Transcribing offline (this may take a few minutes for longer videos)...")
    try:
        text = transcribe_wav(model, wav_path)
    except Exception as e:
        print(f"   [ERROR] Transcription failed: {type(e).__name__}: {e}")
        return
    finally:
        wav_path.unlink(missing_ok=True)

    out_path = SOURCE_DOCS_DIR / f"{video_path.stem}_offline_transcript.txt"
    header = (
        "NOTE: This transcript was produced by an OFFLINE, LOCAL speech-to-text "
        "engine (Vosk), not a cloud AI model. Accuracy is lower than a "
        "cloud transcription service, especially for jargon, accents, or "
        "background noise - treat as a rough guide to what was discussed, "
        "not a verbatim record. No punctuation/capitalization is applied.\n\n"
    )
    if text.strip():
        out_path.write_text(header + text, encoding="utf-8")
        print(f"   Saved: {out_path} ({len(text)} chars)")
    else:
        out_path.write_text(header + "[No speech detected]", encoding="utf-8")
        print("   [NOTE] No speech detected in this audio.")


def main():
    if len(sys.argv) < 2:
        print("Usage: python transcribe_videos_offline.py <folder containing videos>")
        sys.exit(1)

    try:
        from vosk import Model
    except ImportError:
        print("ERROR: vosk not installed. Run: pip install vosk")
        sys.exit(1)

    model_path = Path(VOSK_MODEL_PATH)
    if not model_path.exists():
        print(f"ERROR: Vosk model folder not found at '{VOSK_MODEL_PATH}'.")
        print("Download a model from https://alphacephei.com/vosk/models, ")
        print("extract it, and copy the whole folder next to this script, ")
        print("then update VOSK_MODEL_PATH at the top of this file if needed.")
        sys.exit(1)

    video_folder = Path(sys.argv[1])
    if not video_folder.exists():
        print(f"ERROR: Folder not found: {video_folder}")
        sys.exit(1)

    SOURCE_DOCS_DIR.mkdir(parents=True, exist_ok=True)
    videos = sorted(p for p in video_folder.iterdir() if p.suffix.lower() in VIDEO_EXTENSIONS)
    if not videos:
        print(f"No video files found in {video_folder}")
        sys.exit(0)

    print(f"Loading Vosk model from {model_path}...")
    from vosk import Model
    model = Model(str(model_path))
    print("Model loaded.")

    print(f"\nFound {len(videos)} video(s) to transcribe offline:")
    for v in videos:
        print(f"  - {v.name}")

    for video in videos:
        process_video(model, video)

    print(f"\nAll done. Transcripts written to {SOURCE_DOCS_DIR}")
    print("You can now run: python main.py")


if __name__ == "__main__":
    main()
