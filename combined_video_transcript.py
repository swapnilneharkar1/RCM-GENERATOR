"""
combined_video_transcript.py - produces ONE unified, chronological transcript
per video combining:
  - SCREEN: what's visible, sampled every ~25s (Azure gpt-5.4-mini vision)
  - SPEECH: what was said, in the same ~25s windows (faster-whisper, running
    LOCALLY on this server's CPU - no Azure/Whisper deployment needed)

WHY faster-whisper INSTEAD OF VOSK:
Your videos may mix Hindi and English (including mid-sentence code-switching
- common in Indian business speech), and you may not be able to get an Azure
Whisper deployment. Vosk requires a separate model per language and cannot
handle switching between them. faster-whisper runs the actual Whisper model
(the same underlying technology an Azure Whisper deployment would use) fully
locally - it was trained on ~100 languages including Hindi and handles
code-switching meaningfully better than any single-language offline model.

This script transcribes audio in the SAME time-windows used for screen
sampling, re-running language detection each window (~25s) - not a perfect
solution for switching languages mid-sentence, but a much better
approximation than deciding one language for an entire 15-30 minute video.

SETUP (one-time, on your internet-connected machine):
1. pip install faster-whisper huggingface_hub
2. Download a model - recommended starting point is the "small" multilingual
   model (~250MB, decent Hindi/English quality, reasonable CPU speed):

   python -c "from huggingface_hub import snapshot_download; print(snapshot_download('Systran/small'))"

   This prints a local folder path when done (usually somewhere under your
   user's .cache folder). Copy that WHOLE FOLDER to the server, into this
   project directory, e.g. rcm_generator/small/
3. On the server: pip install faster-whisper (offline, via your usual
   pip-download-then-transfer workflow - this pulls in ctranslate2,
   tokenizers, onnxruntime as dependencies, so download ALL of those too:
   pip download faster-whisper -d rcm_packages --python-version 314 --platform win_amd64 --only-binary=:all:
   then the usual --no-index --find-links install on the server)
4. Set WHISPER_MODEL_PATH below to match the folder name you copied over.

For better accuracy at the cost of speed/size, "medium" (~1.5GB) or
"large-v3" (~3GB) multilingual models exist under the same Systran/
faster-whisper-<size> naming on Hugging Face - same download/copy process.

USAGE:
    python combined_video_transcript.py "C:\\rcm_generator\\RCM Files"
"""

import os
import sys
import base64
import subprocess
from pathlib import Path

from openai import AzureOpenAI
import config

FFMPEG_PATH = "ffmpeg"
FFPROBE_PATH = "ffprobe"
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".mov", ".avi"}

BASE_DIR = Path(__file__).parent
SOURCE_DOCS_DIR = BASE_DIR / "source_docs"
TEMP_DIR = BASE_DIR / "_temp_combined"

# Must match a real folder you've downloaded and copied over - see setup
# instructions above.
WHISPER_MODEL_PATH = "small"

# Set to True to have Whisper translate everything directly to English as
# it transcribes (Hindi speech -> English text, English speech stays
# English). Set to False to get transcription in the original spoken
# language instead (e.g. Hindi in Devanagari script).
TRANSLATE_TO_ENGLISH = True

# Both SCREEN sampling and SPEECH windows use this same size, so they line
# up in the merged output. Kept at 25s by default; for very long videos the
# code automatically widens this to cap total frames/API calls at ~40.
WINDOW_SECONDS = 25
MIN_WINDOW_SECONDS = 15
MAX_WINDOWS = 40

FRAME_DESCRIPTION_PROMPT = """You are assisting an internal auditor reviewing a screen-recording walkthrough of a microfinance loan management system, for Risk Control Matrix documentation.

Describe this screenshot factually and specifically: what screen/module is shown, visible field labels and entered values, visible buttons/actions/status indicators, any user names or timestamps visible, and anything indicating a maker-checker or approval step.

Be factual - only describe what's actually visible. Keep it to roughly 80-150 words."""

API_KEY = getattr(config, "AZURE_OPENAI_API_KEY", "")
ENDPOINT = getattr(config, "AZURE_OPENAI_ENDPOINT", "")
API_VERSION = getattr(config, "AZURE_OPENAI_API_VERSION", "")
DEPLOYMENT = getattr(config, "AZURE_OPENAI_DEPLOYMENT", "")

client = AzureOpenAI(api_key=API_KEY, azure_endpoint=ENDPOINT, api_version=API_VERSION)


# ---------- shared helpers ----------

def get_duration_seconds(video_path: Path) -> float:
    result = subprocess.run(
        [FFPROBE_PATH, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def format_timestamp(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def compute_interval(duration: float) -> float:
    interval = WINDOW_SECONDS
    if duration and duration / interval > MAX_WINDOWS:
        interval = max(MIN_WINDOW_SECONDS, duration / MAX_WINDOWS)
    return interval


# ---------- SCREEN half (vision, Azure) ----------

def extract_frames(video_path: Path, out_dir: Path, interval: float) -> list:
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / f"{video_path.stem}_frame_%04d.jpg")
    subprocess.run(
        [FFMPEG_PATH, "-y", "-i", str(video_path),
         "-vf", f"fps=1/{interval}", "-q:v", "3", pattern],
        check=True, capture_output=True,
    )
    frames = sorted(out_dir.glob(f"{video_path.stem}_frame_*.jpg"))
    return [(f, i * interval) for i, f in enumerate(frames)]


def describe_frame(frame_path: Path) -> str:
    with open(frame_path, "rb") as f:
        b64_image = base64.b64encode(f.read()).decode("utf-8")
    response = client.responses.create(
        model=DEPLOYMENT,
        input=[{
            "role": "user",
            "content": [
                {"type": "input_text", "text": FRAME_DESCRIPTION_PROMPT},
                {"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64_image}"},
            ],
        }],
        max_output_tokens=300,
    )
    text = getattr(response, "output_text", None)
    if text:
        return text
    chunks = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) == "message":
            for c in getattr(item, "content", []) or []:
                if getattr(c, "type", None) in ("output_text", "text"):
                    chunks.append(getattr(c, "text", ""))
    return "\n".join(chunks)


# ---------- SPEECH half (faster-whisper, offline, multilingual) ----------

def extract_audio_windows(video_path: Path, out_dir: Path, interval: float) -> list:
    """Splits audio into interval-second chunks - returns [(chunk_path, start_seconds)]."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = str(out_dir / f"{video_path.stem}_audio_%04d.wav")
    subprocess.run(
        [FFMPEG_PATH, "-y", "-i", str(video_path),
         "-vn", "-ar", "16000", "-ac", "1",
         "-f", "segment", "-segment_time", str(interval),
         pattern],
        check=True, capture_output=True,
    )
    chunks = sorted(out_dir.glob(f"{video_path.stem}_audio_*.wav"))
    return [(c, i * interval) for i, c in enumerate(chunks)]


def transcribe_audio_chunk(whisper_model, chunk_path: Path) -> tuple:
    """Returns (text, detected_language). language=None lets Whisper detect
    per-chunk - re-detecting every ~25s window is the practical compromise
    for videos where speakers switch between Hindi and English.
    task="translate" (when TRANSLATE_TO_ENGLISH is True) tells Whisper to
    output English text regardless of the spoken language, in one pass -
    this is Whisper's native translation mode, not a separate step."""
    task = "translate" if TRANSLATE_TO_ENGLISH else "transcribe"
    segments, info = whisper_model.transcribe(
        str(chunk_path), language=None, task=task, vad_filter=True,
    )
    text = " ".join(seg.text.strip() for seg in segments)
    return text.strip(), getattr(info, "language", "unknown")


# ---------- combine ----------

def process_video(whisper_model, video_path: Path):
    print(f"\n-> {video_path.name}")
    try:
        duration = get_duration_seconds(video_path)
        print(f"   Duration: {duration/60:.1f} min")
    except Exception as e:
        print(f"   [warning] Could not read duration ({e})")
        duration = None

    interval = compute_interval(duration) if duration else WINDOW_SECONDS

    # --- SPEECH (local faster-whisper) ---
    audio_dir = TEMP_DIR / f"{video_path.stem}_audio"
    print("   Extracting + transcribing audio (local faster-whisper, multilingual)...")
    speech_windows = {}
    try:
        audio_chunks = extract_audio_windows(video_path, audio_dir, interval)
        for i, (chunk_path, start) in enumerate(audio_chunks, start=1):
            try:
                text, lang = transcribe_audio_chunk(whisper_model, chunk_path)
                if text:
                    speech_windows[int(start)] = f"[{lang}] {text}"
                print(f"     Audio window {i}/{len(audio_chunks)} ({format_timestamp(start)}, "
                      f"detected: {lang})")
            except Exception as e:
                print(f"     [ERROR] Audio window {i} failed: {type(e).__name__}: {e}")
            finally:
                chunk_path.unlink(missing_ok=True)
    except subprocess.CalledProcessError as e:
        print(f"   [ERROR] Audio extraction failed: {e.stderr.decode(errors='ignore')[:300]}")

    # --- SCREEN (Azure vision) ---
    frame_dir = TEMP_DIR / video_path.stem
    print("   Extracting + describing frames (Azure vision)...")
    screen_windows = {}
    try:
        frames = extract_frames(video_path, frame_dir, interval)
        for i, (frame_path, timestamp) in enumerate(frames, start=1):
            print(f"     Frame {i}/{len(frames)} ({format_timestamp(timestamp)})...")
            try:
                screen_windows[int(timestamp)] = describe_frame(frame_path)
            except Exception as e:
                screen_windows[int(timestamp)] = f"[Description failed: {e}]"
            finally:
                frame_path.unlink(missing_ok=True)
    except subprocess.CalledProcessError as e:
        print(f"   [ERROR] Frame extraction failed: {e.stderr.decode(errors='ignore')[:300]}")

    # --- merge, sorted by timestamp ---
    all_timestamps = sorted(set(list(speech_windows.keys()) + list(screen_windows.keys())))
    lines = []
    for ts in all_timestamps:
        label = format_timestamp(ts)
        if ts in screen_windows:
            lines.append(f"[{label}] SCREEN: {screen_windows[ts]}")
        if ts in speech_windows:
            lines.append(f"[{label}] SPEECH: {speech_windows[ts]}")

    out_path = SOURCE_DOCS_DIR / f"{video_path.stem}_combined_transcript.txt"
    header = (
        f"NOTE: Combined walkthrough transcript for '{video_path.name}'. "
        f"SCREEN lines come from AI vision description of sampled frames "
        f"(Azure {DEPLOYMENT}). SPEECH lines come from LOCAL offline "
        f"transcription (faster-whisper, multilingual - detected source "
        f"language per window shown in brackets"
        f"{', translated to English' if TRANSLATE_TO_ENGLISH else ''}). "
        f"Language re-detected every ~{interval:.0f}s so it can adapt "
        f"across a Hindi/English mixed conversation, though mid-sentence "
        f"code-switching within a single window may still be imperfect. "
        f"Treat as directional evidence; verify precise details against "
        f"the source video where needed.\n\n"
    )
    out_path.write_text(header + "\n".join(lines), encoding="utf-8")
    print(f"   Saved: {out_path}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python combined_video_transcript.py <folder containing videos>")
        sys.exit(1)
    if not API_KEY or "PASTE-YOUR-AZURE-KEY-HERE" in API_KEY:
        print("ERROR: config.py Azure key not set - needed for the SCREEN half.")
        sys.exit(1)

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("ERROR: faster-whisper not installed - needed for the SPEECH half. "
              "Run: pip install faster-whisper")
        sys.exit(1)

    model_path = Path(WHISPER_MODEL_PATH)
    if not model_path.exists():
        print(f"ERROR: Whisper model folder not found at '{WHISPER_MODEL_PATH}' - "
              f"needed for the SPEECH half. See the setup instructions at the "
              f"top of this file.")
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

    print(f"Loading faster-whisper model from {model_path} (CPU, int8)...")
    whisper_model = WhisperModel(str(model_path), device="cpu", compute_type="int8")
    print("Model loaded.")

    print(f"\nFound {len(videos)} video(s):")
    for v in videos:
        print(f"  - {v.name}")
    print(f"\nEach video: local multilingual audio transcription + Azure "
          f"vision frame descriptions (~1 API call per sampled frame). "
          f"Expect this to take a while across all videos.")

    for video in videos:
        process_video(whisper_model, video)

    print(f"\nAll done. Combined transcripts written to {SOURCE_DOCS_DIR}")
    print("You can now run: python main.py")


if __name__ == "__main__":
    main()
