"""
analyze_video_frames.py - describes what's ON SCREEN in your walkthrough
videos by extracting frames and sending them to your EXISTING gpt-5.4-mini
deployment (which can read images, not just text) via the Responses API.

WHY THIS INSTEAD OF AUDIO TRANSCRIPTION:
Your Azure resource only has a text/vision deployment (gpt-5.4-mini), no
Whisper deployment - so audio transcription (transcribe_videos.py) can't
work until your Azure admin provisions one. These videos also look like
silent screen-recording walkthroughs (system demos), where the real
evidence - approvals clicked, fields filled, user names, statuses - is
visual, not spoken. This script captures exactly that, using infrastructure
you already have.

HOW IT WORKS:
1. For each video, extracts a frame roughly every 20-60 seconds (spaced out
   automatically so a long video doesn't produce hundreds of frames -
   capped around 30 frames per video by default).
2. Sends each frame to gpt-5.4-mini with a prompt asking it to describe,
   factually, what's on screen: module/screen name, visible fields and
   values, buttons/approval actions, user names, statuses, timestamps.
3. Concatenates all frame descriptions (each labeled with its timestamp in
   the video) into a single .txt file per video in source_docs/, which
   main.py picks up automatically like any other document.

LIMITATIONS - be upfront about these with your audit team:
- This captures WHAT'S VISIBLE in sampled frames, not a continuous
  play-by-play. A fast action between two sampled frames could be missed.
  It's a reasonable proxy for a walkthrough narrative, not a frame-perfect
  transcript.
- Frame descriptions are the model's best factual reading of pixels -
  useful as directional evidence, but for anything requiring precise
  verification (exact approver name spelling, exact timestamp), the
  original video remains the source of truth and should be referenced too.
- Cost/time scales with (number of videos) x (frames per video) - one
  vision API call per frame.

USAGE:
    python analyze_video_frames.py "C:\\rcm_generator\\RCM Files"
"""

import os
import sys
import base64
import subprocess
from pathlib import Path

from openai import AzureOpenAI
import config

BASE_DIR = Path(__file__).parent
SOURCE_DOCS_DIR = BASE_DIR / "source_docs"
TEMP_FRAMES_DIR = BASE_DIR / "_temp_frames"

FFMPEG_PATH = "ffmpeg"
FFPROBE_PATH = "ffprobe"

VIDEO_EXTENSIONS = {".mp4", ".webm", ".mkv", ".mov", ".avi"}

# Aim for roughly this many frames per video, regardless of length - keeps
# API call count (and cost/time) predictable. A 15-min video gets a frame
# every ~30s; a 32-min video gets a frame every ~64s.
TARGET_FRAMES_PER_VIDEO = 30
MIN_INTERVAL_SECONDS = 15  # never sample more often than this, even for short videos

FRAME_DESCRIPTION_PROMPT = """You are assisting an internal auditor reviewing a screen-recording walkthrough of a microfinance loan management system, for the purpose of documenting operational controls (Risk Control Matrix preparation).

Describe this screenshot factually and specifically. Cover, where visible:
1. What screen, module, or workflow step is being shown (e.g. "loan disbursement approval screen", "KYC document upload").
2. Any visible field labels and their entered values (e.g. loan amount, customer name, dates) - transcribe text you can actually read.
3. Any buttons, action items, or status indicators visible (e.g. "Approve", "Reject", "Pending Checker Review", "Submitted").
4. Any user names, employee IDs, roles, or timestamps visible on screen.
5. Anything indicating a maker-checker step, an approval hierarchy, or a system-generated audit trail entry.

Be factual and specific - only describe what is actually visible. If text is too small/blurry to read confidently, say so rather than guessing. If the screen is a generic loading/blank screen with no useful content, say that briefly rather than padding with speculation.

Keep your response focused and evidence-oriented, roughly 100-200 words."""

_configured_key = getattr(config, "AZURE_OPENAI_API_KEY", "")
API_KEY = _configured_key if _configured_key and "PASTE-YOUR-AZURE-KEY-HERE" not in _configured_key \
    else os.environ.get("AZURE_OPENAI_API_KEY", "")
ENDPOINT = getattr(config, "AZURE_OPENAI_ENDPOINT", "")
API_VERSION = getattr(config, "AZURE_OPENAI_API_VERSION", "")
DEPLOYMENT = getattr(config, "AZURE_OPENAI_DEPLOYMENT", "")

client = AzureOpenAI(api_key=API_KEY, azure_endpoint=ENDPOINT, api_version=API_VERSION)


def get_duration_seconds(video_path: Path) -> float:
    result = subprocess.run(
        [FFPROBE_PATH, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def extract_frames(video_path: Path, out_dir: Path) -> list:
    """Returns list of (frame_path, timestamp_seconds) tuples."""
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = get_duration_seconds(video_path)
    interval = max(MIN_INTERVAL_SECONDS, duration / TARGET_FRAMES_PER_VIDEO)

    pattern = str(out_dir / f"{video_path.stem}_frame_%04d.jpg")
    subprocess.run(
        [FFMPEG_PATH, "-y", "-i", str(video_path),
         "-vf", f"fps=1/{interval}",
         "-q:v", "3",  # good quality, reasonable file size
         pattern],
        check=True, capture_output=True,
    )
    frames = sorted(out_dir.glob(f"{video_path.stem}_frame_*.jpg"))
    return [(f, i * interval) for i, f in enumerate(frames)]


def describe_frame(frame_path: Path) -> str:
    with open(frame_path, "rb") as f:
        b64_image = base64.b64encode(f.read()).decode("utf-8")

    response = client.responses.create(
        model=DEPLOYMENT,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": FRAME_DESCRIPTION_PROMPT},
                    {"type": "input_image", "image_url": f"data:image/jpeg;base64,{b64_image}"},
                ],
            }
        ],
        max_output_tokens=400,
    )
    text = getattr(response, "output_text", None)
    if text:
        return text
    chunks = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) == "message":
            for content in getattr(item, "content", []) or []:
                if getattr(content, "type", None) in ("output_text", "text"):
                    chunks.append(getattr(content, "text", ""))
    return "\n".join(chunks)


def format_timestamp(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def process_video(video_path: Path):
    print(f"\n-> {video_path.name}")
    try:
        duration = get_duration_seconds(video_path)
        print(f"   Duration: {duration/60:.1f} min")
    except Exception as e:
        print(f"   [warning] Could not read duration ({e})")

    frame_dir = TEMP_FRAMES_DIR / video_path.stem
    print("   Extracting frames...")
    try:
        frames = extract_frames(video_path, frame_dir)
    except subprocess.CalledProcessError as e:
        print(f"   [ERROR] ffmpeg failed: {e.stderr.decode(errors='ignore')[:500]}")
        return
    print(f"   {len(frames)} frame(s) to describe")

    descriptions = []
    for i, (frame_path, timestamp) in enumerate(frames, start=1):
        ts_label = format_timestamp(timestamp)
        print(f"   Describing frame {i}/{len(frames)} ({ts_label})...")
        try:
            desc = describe_frame(frame_path)
            descriptions.append(f"[Timestamp {ts_label}]\n{desc}")
        except Exception as e:
            print(f"   [ERROR] Frame {i} failed: {type(e).__name__}: {e}")
            descriptions.append(f"[Timestamp {ts_label}]\n[Description failed: {e}]")
        finally:
            frame_path.unlink(missing_ok=True)

    out_path = SOURCE_DOCS_DIR / f"{video_path.stem}_frames_description.txt"
    header = (f"NOTE: This is a vision-based description of sampled frames from "
              f"'{video_path.name}', taken roughly every "
              f"{(frames[1][1] - frames[0][1]) if len(frames) > 1 else 'N/A'} seconds. "
              f"It is NOT a frame-by-frame transcript - fast actions between "
              f"samples may be missed. Treat as directional walkthrough "
              f"evidence; verify precise details against the source video "
              f"where needed.\n\n")
    out_path.write_text(header + "\n\n".join(descriptions), encoding="utf-8")
    print(f"   Saved: {out_path}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python analyze_video_frames.py <folder containing videos>")
        sys.exit(1)
    if not API_KEY or "PASTE-YOUR-AZURE-KEY-HERE" in API_KEY:
        print("ERROR: No Azure API key found - set it in config.py first.")
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

    print(f"Found {len(videos)} video(s) to analyze:")
    for v in videos:
        print(f"  - {v.name}")
    print(f"\nSampling ~{TARGET_FRAMES_PER_VIDEO} frames per video "
          f"(min {MIN_INTERVAL_SECONDS}s apart). This makes one vision API "
          f"call per frame - expect this to take a while for 11 videos.")

    for video in videos:
        process_video(video)

    print(f"\nAll done. Frame descriptions written to {SOURCE_DOCS_DIR}")
    print("You can now run: python main.py")


if __name__ == "__main__":
    main()
