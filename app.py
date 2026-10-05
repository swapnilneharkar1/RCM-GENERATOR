"""
app.py - Streamlit web interface for the RCM Generator.

This is a thin UI wrapper around your EXISTING, working pipeline - the
actual pipeline calls live in pipeline_core.py (shared with watch_folder.py,
the shared-network-folder alternative front-end), which in turn calls your
unmodified combined_video_transcript.py and main.py functions:

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
    python -m streamlit run app.py

Then anyone on the internal network can open:
    http://<this-server's-IP-or-hostname>:8501
in a browser - no SSH/RDP or server access needed. See README_APP.md.

If your network team won't open a new port for browser access, see
watch_folder.py instead (README_DROPBOX.md) - same pipeline, triggered by
dropping files into a shared network folder rather than a web page.
"""

import shutil
import threading
import time
import traceback
import uuid
from pathlib import Path

import streamlit as st

import auth

BASE_DIR = Path(__file__).parent
SESSIONS_DIR = BASE_DIR / "sessions"

# ---- Background job tracking ----
# The actual pipeline run (transcript step + all RCM segments + gap-check)
# can take many minutes. Running it directly inside a Streamlit script run
# (blocking inside st.spinner) holds the browser<->server connection
# perfectly idle for that whole time - no bytes flow either direction - and
# any proxy/load-balancer/firewall in between that closes idle connections
# after a timeout window will silently kill it, so the page just looks
# frozen forever even though the server is still working.
#
# Fix: run the pipeline in a background thread and have the page poll +
# auto-refresh every few seconds while it works. That keeps the connection
# alive with real traffic (defeating idle-timeout kills) and gives a live
# "still working" heartbeat instead of one long silent wait.
#
# IMPORTANT: Streamlit re-executes this whole file top-to-bottom on every
# rerun (including the auto-refresh reruns below), so a plain module-level
# `_JOBS = {}` would be wiped back to empty on every single rerun - it would
# never actually remember a running job. st.cache_resource is what gives us
# an object that really persists across reruns (and across all sessions,
# which is exactly what we need since the job dict is written to by a
# background thread and read back after the page reruns).
@st.cache_resource
def _get_jobs_state():
    return {"jobs": {}, "lock": threading.Lock()}


_jobs_state = _get_jobs_state()
_JOBS = _jobs_state["jobs"]
_JOBS_LOCK = _jobs_state["lock"]
POLL_SECONDS = 4


def _run_job_in_background(job_id: str, session_dir: Path, video_paths: list):
    try:
        output_path = pipeline_core.run_full_pipeline(session_dir, video_paths)
        with _JOBS_LOCK:
            _JOBS[job_id] = {"status": "done", "output_path": str(output_path)}
    except Exception as e:
        with _JOBS_LOCK:
            _JOBS[job_id] = {
                "status": "error",
                "error": str(e),
                "traceback": traceback.format_exc(),
            }

VIDEO_TYPES = ["mp4", "webm", "mkv", "mov", "avi"]
DOC_TYPES = ["pdf", "docx", "pptx", "txt", "md"]

st.set_page_config(page_title="RCM Generator", page_icon="\U0001F4CB", layout="centered")

# ---- Auth gate: nothing below this line renders until login succeeds ----
username = auth.login_gate()
auth.logout_button()

# ---- Import the pipeline (only after page is set up, so an import error
# shows inside the app instead of a blank crash) ----
try:
    import pipeline_core
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

st.title("RCM Generator")
st.caption(
    "Upload walkthrough videos, supporting documents, and (optionally) an "
    "existing RCM Excel file. Click Generate to run the same pipeline used "
    "on the server, and download the finished RCM when it's done."
)

if not pipeline_core.config_is_ready():
    st.error(
        "The Azure OpenAI connection isn't configured yet (config.py). "
        "Ask your admin to set AZURE_OPENAI_API_KEY / AZURE_OPENAI_ENDPOINT "
        "before this app can generate an RCM."
    )
    st.stop()


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
    elif st.session_state.get("job_id"):
        st.warning("A job is already running - wait for it to finish first.")
    else:
        session_dir = new_session_dir()
        video_paths = save_uploads(session_dir, videos, docs, existing_rcm)
        job_id = uuid.uuid4().hex
        with _JOBS_LOCK:
            _JOBS[job_id] = {"status": "running"}
        thread = threading.Thread(
            target=_run_job_in_background,
            args=(job_id, session_dir, video_paths),
            daemon=True,
        )
        thread.start()
        st.session_state["job_id"] = job_id
        st.session_state["job_session_dir"] = str(session_dir)
        st.rerun()

# ---- Poll the background job, if one is running ----
# Refreshing on a timer (instead of one long blocking call) is what keeps
# the connection alive through idle-timeout proxies/firewalls - see the
# comment on _JOBS above.
job_id = st.session_state.get("job_id")
if job_id:
    with _JOBS_LOCK:
        job = dict(_JOBS.get(job_id, {"status": "running"}))

    status = job.get("status")
    if status == "running":
        st.info(
            f"Processing, please wait... this page refreshes itself every "
            f"{POLL_SECONDS}s, so you can leave it open (or come back later - "
            f"progress isn't lost if you close the tab)."
        )
        with st.spinner("Working..."):
            time.sleep(POLL_SECONDS)
        st.rerun()
    elif status == "done":
        output_path = Path(job["output_path"])
        st.session_state["last_output_path"] = str(output_path)
        st.session_state["last_output_name"] = output_path.name
        del st.session_state["job_id"]
        st.session_state.pop("job_session_dir", None)
        with _JOBS_LOCK:
            _JOBS.pop(job_id, None)
        st.success("RCM generated.")
    elif status == "error":
        st.error(f"RCM generation failed: {job.get('error', 'unknown error')}")
        st.code(job.get("traceback", ""))
        session_dir = st.session_state.get("job_session_dir")
        if session_dir:
            shutil.rmtree(session_dir, ignore_errors=True)
        del st.session_state["job_id"]
        st.session_state.pop("job_session_dir", None)
        with _JOBS_LOCK:
            _JOBS.pop(job_id, None)

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
