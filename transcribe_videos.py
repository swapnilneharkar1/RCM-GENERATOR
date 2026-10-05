"""
transcribe_videos.py - turns your walkthrough videos into .txt transcripts
that document_loader.py can pick up automatically.

WHY THIS IS SEPARATE FROM main.py:
Transcription is a one-time, slow, API-cost-incurring step per video. You
don't want to re-transcribe every time you tweak a prompt and re-run
main.py. Run this once per video (or whenever a video changes), then run
main.py as many times as you like against the resulting .txt files.

WHAT THIS DOES NOT DO:
It transcribes AUDIO only - narration, spoken explanation of what's
happening on screen. It does NOT read on-screen text, click locations,
approval button presses, or user names typed into forms. If your videos
are silent screen recordings with no narration, this script will produce
empty/near-empty transcripts and you'll need frame-extraction + vision
description instead (a different, heavier approach - ask me to build it if
your videos turn out to be silent).

REQUIREMENTS:
- ffmpeg.exe (and ffprobe.exe) available - either on PATH or set FFMPEG_PATH
  below to a full path. ffmpeg is NOT a pip package; download the "essentials"
  Windows build from https://www.gyan.dev/ffmpeg/builds/ on your internet-
  connected machine, extract it, and copy ffmpeg.exe + ffprobe.exe next to
  this script (or anywhere, then set FFMPEG_PATH accordingly).
- Your OpenAI API key configured in config.py (same one used by main.py).

USAGE:
    python transcribe_videos.py "C:\\rcm_generator\\RCM Files"

    This scans that folder for .mp4/.webm/.mkv/.mov files, extracts audio,
    transcribes each, and writes <video_name>_transcript.txt into
    source_docs/ automatically.
"""

import os
import sys
import subprocess
import math
from pathlib import Path

from openai import AzureOpenAI
import config

BASE_DIR = Path(__file__).parent
SOURCE_DOCS_DIR = BASE_DIR / "source_docs"
TEMP_AUDIO_DIR = BASE_DIR / "_temp_audio"

# Set this if ffmpeg.exe isn't on PATH, e.g. r"C:\rcm_generator\rcm_generator\ffmpeg.exe"
FFMPEG_PATH = "ffmpeg"
FFPROBE_PATH = "ffprobe"

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".mov", ".avi"}

# OpenAI's audio transcription endpoint has a ~25MB file size limit.
# We extract audio as low-bitrate mono mp3 (plenty for speech) and, if still
# too large for a long video, split into N-minute chunks.
CHUNK_SECONDS = 600  # 10-minute chunks - safely under 25MB at 64kbps mono

_configured_key = getattr(config, "AZURE_OPENAI_API_KEY", "")
API_KEY = _configured_key if _configured_key and "PASTE-YOUR-AZURE-KEY-HERE" not in _configured_key \
    else os.environ.get("AZURE_OPENAI_API_KEY", "")
ENDPOINT = getattr(config, "AZURE_OPENAI_ENDPOINT", "")
API_VERSION = getattr(config, "AZURE_OPENAI_API_VERSION", "")
WHISPER_DEPLOYMENT = getattr(config, "AZURE_OPENAI_WHISPER_DEPLOYMENT", "whisper-1")

client = AzureOpenAI(api_key=API_KEY, azure_endpoint=ENDPOINT, api_version=API_VERSION)


def get_duration_seconds(video_path: Path) -> float:
    result = subprocess.run(
        [FFPROBE_PATH, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def extract_audio_chunks(video_path: Path, out_dir: Path) -> list:
    """Extracts audio as mono 64kbps mp3, split into CHUNK_SECONDS pieces."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / f"{video_path.stem}_chunk_%03d.mp3")
    subprocess.run(
        [FFMPEG_PATH, "-y", "-i", str(video_path),
         "-vn", "-ar", "16000", "-ac", "1", "-b:a", "64k",
         "-f", "segment", "-segment_time", str(CHUNK_SECONDS),
         pattern],
        check=True, capture_output=True,
    )
    chunks = sorted(out_dir.glob(f"{video_path.stem}_chunk_*.mp3"))
    return chunks


def transcribe_chunk(chunk_path: Path) -> str:
    with open(chunk_path, "rb") as f:
        result = client.audio.transcriptions.create(
            model=WHISPER_DEPLOYMENT,
            file=f,
        )
    return result.text


def process_video(video_path: Path):
    print(f"\n-> {video_path.name}")
    try:
        duration = get_duration_seconds(video_path)
        print(f"   Duration: {duration/60:.1f} min")
    except Exception as e:
        print(f"   [warning] Could not read duration ({e}), proceeding anyway")

    chunk_dir = TEMP_AUDIO_DIR / video_path.stem
    print("   Extracting audio...")
    try:
        chunks = extract_audio_chunks(video_path, chunk_dir)
    except subprocess.CalledProcessError as e:
        print(f"   [ERROR] ffmpeg failed: {e.stderr.decode(errors='ignore')[:500]}")
        return
    print(f"   {len(chunks)} audio chunk(s) to transcribe")

    full_transcript = []
    any_chunk_failed = False
    for i, chunk in enumerate(chunks, start=1):
        print(f"   Transcribing chunk {i}/{len(chunks)}...")
        try:
            text = transcribe_chunk(chunk)
            full_transcript.append(text)
        except Exception as e:
            any_chunk_failed = True
            print(f"   [ERROR] Chunk {i} failed: {type(e).__name__}: {e}")
        finally:
            chunk.unlink(missing_ok=True)  # clean up as we go

    out_path = SOURCE_DOCS_DIR / f"{video_path.stem}_transcript.txt"
    out_path.write_text("\n\n".join(full_transcript), encoding="utf-8")
    print(f"   Saved: {out_path}")

    if any_chunk_failed:
        print("   [WARNING] One or more chunks FAILED to transcribe (see "
              "errors above) - this transcript is INCOMPLETE, not "
              "necessarily because the video is silent. Run "
              "diagnose_connection.py to check the underlying API "
              "connection before assuming this video has no narration.")
    elif not full_transcript or not "".join(full_transcript).strip():
        print("   [NOTE] All chunks transcribed successfully but returned "
              "empty text - this video genuinely appears to have no "
              "narration/speech (silent screen recording). Frame-based "
              "vision description would be needed instead for this one.")


def main():
    if len(sys.argv) < 2:
        print("Usage: python transcribe_videos.py <folder containing videos>")
        sys.exit(1)
    if not API_KEY:
        print("ERROR: No API key found - set it in config.py first.")
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

    print(f"Found {len(videos)} video(s) to transcribe:")
    for v in videos:
        print(f"  - {v.name}")

    for video in videos:
        process_video(video)

    print(f"\nAll done. Transcripts written to {SOURCE_DOCS_DIR}")
    print("You can now run: python main.py")


if __name__ == "__main__":
    main()
