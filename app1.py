"""
app.py - Streamlit web interface for the RCM Generator.

This is a thin UI wrapper around your EXISTING, working pipeline - it does
not reimplement the transcript step or the RCM-generation step. It calls the
same functions your combined_video_transcript.py and main.py already use:

    combined_video_transcript.process_video(...)   -> transcript step
    document_loader.load_all_documents(...)
    document_loader.load_all_rcm_excels(...)
    main.run_segment(...) / main.run_gap_check(...) -> RCM generation step
    excel_writer.write_rcm_workbook(...)            -> final .xlsx

Why a per-session working folder:
Several end users may use this at the same time. Each browser session gets
its own folder under sessions/<username>_<timestamp>_<random>/ so uploads,
transcripts, and output from one person's run never mix with another's.

Run it (on the server, same folder as main.py):
    streamlit run app.py --server.address 0.0.0.0 --server.port 8501

Then anyone on the internal network can open:
    http://<this-server's-IP-or-hostname>:8501
in a browser - no SSH/RDP or server access needed. See README_APP.md.
"""

import shutil
import sys
import time
import traceback
import uuid
from pathlib import Path

import streamlit as st

import auth

BASE_DIR = Path(__file__).parent
SESSIONS_DIR = BASE_DIR / "sessions"

VIDEO_TYPES = ["mp4", "webm", "mkv", "mov", "avi"]
DOC_TYPES = ["pdf", "docx", "pptx", "txt", "md"]

st.set_page_config(page_title="RCM Generator", page_icon="\U0001F4CB", layout="centered")

# ---- Auth gate: nothing below this line renders until login succeeds ----
username = auth.login_gate()
auth.logout_button()

# ---- Import the existing pipeline modules (only after page is set up, so an
# import error shows inside the app instead of a blank crash) ----
try:
    import config
    import document_loader
    import excel_writer
    from prompts.segments import SEGMENTS
    import main as rcm_main
    import combined_video_transcript as vid_mod
except Exception as e:
    st.error(
        "Could not load the RCM generator pipeline modules "
        "(main.py / document_loader.py / excel_writer.py / prompts/ / "
        "combined_video_transcript.py). Make sure app.py is in the same "
        "folder as those files.\n\n"
        f"Error: {e}"
    )
    st.code(traceback.format_exc())
    st.stop()


def config_is_ready() -> bool:
    key = getattr(config, "AZURE_OPENAI_API_KEY", "")
    endpoint = getattr(config, "AZURE_OPENAI_ENDPOINT", "")
    return bool(key) and "PASTE-YOUR-AZURE-KEY-HERE" not in key and bool(endpoint)


st.title("RCM Generator")
st.caption(
    "Upload walkthrough videos, supporting documents, and (optionally) an "
    "existing RCM Excel file. Click Generate to run the same pipeline used "
    "on the server, and download the finished RCM when it's done."
)

if not config_is_ready():
    st.error(
        "The Azure OpenAI connection isn't configured yet (config.py). "
        "Ask your admin to set AZURE_OPENAI_API_KEY / AZURE_OPENAI_ENDPOINT "
        "before this app can generate an RCM."
    )
    st.stop()

# ---- Whisper model: loaded once per server process and reused across users
# and requests (loading it fresh per request would be very slow). Only
# triggered the first time someone actually uploads a video. ----
@st.cache_resource(show_spinner=False)
def get_whisper_model():
    from faster_whisper import WhisperModel

    model_path = Path(vid_mod.WHISPER_MODEL_PATH)
    if not model_path.is_absolute():
        model_path = vid_mod.BASE_DIR / model_path
    if not model_path.exists():
        raise FileNotFoundError(
            f"Whisper model folder not found at '{model_path}'. See the setup "
            f"instructions at the top of combined_video_transcript.py."
        )
    return WhisperModel(str(model_path), device="cpu", compute_type="int8")


def new_session_dir() -> Path:
    label = f"{username}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    session_dir = SESSIONS_DIR / label
    (session_dir / "source_docs").mkdir(parents=True, exist_ok=True)
    (session_dir / "videos").mkdir(parents=True, exist_ok=True)
    (session_dir / "output").mkdir(parents=True, exist_ok=True)
    return session_dir


def save_uploads(session_dir: Path, videos, docs, existing_rcm):
    video_paths = []
    for f in videos or []:
        dest = session_dir / "videos" / f.name
        dest.write_bytes(f.getbuffer())
        video_paths.append(dest)

    for f in docs or []:
        dest = session_dir / "source_docs" / f.name
        dest.write_bytes(f.getbuffer())

    if existing_rcm is not None:
        dest = session_dir / "source_docs" / existing_rcm.name
        dest.write_bytes(existing_rcm.getbuffer())

    return video_paths


def run_transcript_step(session_dir: Path, video_paths: list):
    """Same work as combined_video_transcript.py's main(), but scoped to this
    session's folders instead of the project-wide source_docs/ folder."""
    if not video_paths:
        return

    whisper_model = get_whisper_model()

    # Point the existing module's globals at THIS session's folders instead
    # of its normal project-wide defaults, so concurrent users don't collide.
    vid_mod.SOURCE_DOCS_DIR = session_dir / "source_docs"
    vid_mod.TEMP_DIR = session_dir / "_temp_video"

    for video_path in video_paths:
        vid_mod.process_video(whisper_model, video_path)


def run_rcm_generation_step(session_dir: Path) -> Path:
    """Same work as main.py's main(), scoped to this session's folders."""
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


# ---- Combined upload + generate page ----

st.subheader("1. Upload your files")
videos = st.file_uploader(
    "Walkthrough videos",
    type=VIDEO_TYPES,
    accept_multiple_files=True,
    help="Videos with narration are transcribed with local speech-to-text; "
         "silent screen recordings are still useful (screen content is "
         "described from sampled frames).",
)
docs = st.file_uploader(
    "Supporting documents (SOPs, PPG, RBI directions, etc.)",
    type=DOC_TYPES,
    accept_multiple_files=True,
)
existing_rcm = st.file_uploader(
    "Optional: existing RCM Excel file (used as the base to restructure/complete, not overwritten)",
    type=["xlsx"],
)

st.subheader("2. Generate")
generate_clicked = st.button("Generate RCM", type="primary")

if generate_clicked:
    if not videos and not docs and not existing_rcm:
        st.warning("Upload at least one video, document, or existing RCM file first.")
    else:
        session_dir = new_session_dir()
        with st.spinner("Processing, please wait..."):
            try:
                video_paths = save_uploads(session_dir, videos, docs, existing_rcm)
                run_transcript_step(session_dir, video_paths)
                output_path = run_rcm_generation_step(session_dir)
                st.session_state["last_output_path"] = str(output_path)
                st.session_state["last_output_name"] = output_path.name
            except Exception as e:
                st.error(f"RCM generation failed: {e}")
                st.code(traceback.format_exc())
                shutil.rmtree(session_dir, ignore_errors=True)
                st.stop()

        st.success("RCM generated.")

if st.session_state.get("last_output_path"):
    output_path = Path(st.session_state["last_output_path"])
    if output_path.exists():
        st.subheader("3. Download")
        st.download_button(
            "Download RCM Excel",
            data=output_path.read_bytes(),
            file_name=st.session_state.get("last_output_name", "RCM_MicroFinance_Loans.xlsx"),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
