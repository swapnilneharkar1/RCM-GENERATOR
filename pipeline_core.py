"""
pipeline_core.py - the actual "run the pipeline on this folder" logic,
shared by BOTH front-ends:
    - app.py           (the Streamlit web page - used when reachable by browser)
    - watch_folder.py  (the shared-network-folder alternative - used when
                         end users can't reach a new port, only a file share)

Both call the exact same functions here, which in turn call your existing,
unmodified main.py / combined_video_transcript.py / document_loader.py /
excel_writer.py functions - nothing about how the RCM is generated changes
depending on which front-end triggered it.
"""

import threading
from pathlib import Path

import config
import document_loader
import excel_writer
from prompts.segments import SEGMENTS
import main as rcm_main
import combined_video_transcript as vid_mod

_whisper_model = None
_whisper_lock = threading.Lock()


def config_is_ready() -> bool:
    key = getattr(config, "AZURE_OPENAI_API_KEY", "")
    endpoint = getattr(config, "AZURE_OPENAI_ENDPOINT", "")
    return bool(key) and "PASTE-YOUR-AZURE-KEY-HERE" not in key and bool(endpoint)


def _resolve_whisper_model_source() -> str:
    """
    Decide where to load the Whisper model from:
      1) the path configured in combined_video_transcript.py (if that folder exists)
      2) the local 'faster-whisper-small' folder next to this file (if it exists)
      3) otherwise the model name 'small' - faster-whisper downloads it
         automatically (used on Streamlit Cloud, which has internet access).
    """
    configured = Path(getattr(vid_mod, "WHISPER_MODEL_PATH", "faster-whisper-small"))
    if not configured.is_absolute():
        configured = Path(vid_mod.BASE_DIR) / configured
    if configured.exists():
        return str(configured)

    local_dir = Path(__file__).parent / "faster-whisper-small"
    if local_dir.exists():
        return str(local_dir)

    return "small"


def get_whisper_model():
    """Loaded once per server process (not once per job) and reused - this
    is the slow part (reading the model into memory), so we don't want to
    repeat it for every video or every job."""
    global _whisper_model
    with _whisper_lock:
        if _whisper_model is None:
            from faster_whisper import WhisperModel

            model_source = _resolve_whisper_model_source()
            _whisper_model = WhisperModel(model_source, device="cpu", compute_type="int8")
    return _whisper_model


def run_transcript_step(session_dir: Path, video_paths: list):
    """Same work as combined_video_transcript.py's main(), scoped to this
    job's own folders instead of the project-wide source_docs/ folder, so
    concurrent jobs (from different users, or web + dropbox at once) don't
    collide."""
    if not video_paths:
        return

    whisper_model = get_whisper_model()

    vid_mod.SOURCE_DOCS_DIR = session_dir / "source_docs"
    vid_mod.TEMP_DIR = session_dir / "_temp_video"

    for video_path in video_paths:
        vid_mod.process_video(whisper_model, video_path)


def run_rcm_generation_step(session_dir: Path) -> Path:
    """Same work as main.py's main(), scoped to this job's own folders."""
    source_docs_dir = session_dir / "source_docs"
    output_path = session_dir / "output" / "RCM_MicroFinance_Loans.xlsx"

    all_docs = document_loader.load_all_documents(str(source_docs_dir))
    rcm_rows = document_loader.load_all_rcm_excels(str(source_docs_dir))

    all_rows = []
    for segment in SEGMENTS:
        rows = rcm_main.run_segment(segment, all_docs, rcm_rows)
        all_rows.extend(rows)

    gap_findings = rcm_main.run_gap_check(all_rows) if all_rows else []

    output_path.parent.mkdir(parents=True, exist_ok=True)
    excel_writer.write_rcm_workbook(all_rows, gap_findings, str(output_path))
    return output_path


def run_full_pipeline(session_dir: Path, video_paths: list) -> Path:
    """Convenience wrapper: transcript step (if any videos) + RCM generation
    step, returns the path to the finished .xlsx."""
    run_transcript_step(session_dir, video_paths)
    return run_rcm_generation_step(session_dir)