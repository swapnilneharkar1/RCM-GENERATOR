# RCM Generator - Web Interface (app.py)

This adds a browser-based interface on top of your existing pipeline
(`main.py`, `combined_video_transcript.py`, `document_loader.py`,
`excel_writer.py`, `prompts/`) so end users who don't have direct server
access can generate an RCM themselves: upload videos + documents (+
optionally an existing RCM), click one button, download the result.

It does **not** replace or duplicate your pipeline logic - `app.py` imports
and calls the same functions `main.py` already uses. Nothing about how the
RCM is generated has changed; only how someone triggers it has.

## New files added

| File | Purpose |
|---|---|
| `app.py` | The Streamlit page: upload, Generate button, spinner, download. |
| `auth.py` | Per-user login (stdlib-only, no new dependency beyond Streamlit). |
| `create_user.py` | Admin CLI to add/remove accounts. |
| `users.json` | Created automatically the first time you add a user - holds salted password hashes, never plain-text passwords. |
| `sessions/` | Created automatically at runtime - one folder per generation run, so concurrent users don't collide. Safe to delete old subfolders periodically to reclaim disk space. |

## 1. Get Streamlit onto the server (no internet needed)

Same offline workflow you already used for `faster-whisper`:

On a machine **with** internet access:
```bash
pip download streamlit -d rcm_packages --python-version 314 --platform win_amd64 --only-binary=:all:
```
This pulls Streamlit and its dependencies as `.whl` files into `rcm_packages/`.
Copy that folder (merge into your existing `rcm_packages/` folder) to the
server.

On the server (no internet):
```powershell
pip install --no-index --find-links=rcm_packages streamlit
```

If any dependency wheel is missing for `win_amd64`/your Python version, the
install will say exactly which package/version is missing - download just
that one the same way and re-run the install.

## 2. Create the first user account

On the server, in the `rcm_generator` folder:
```powershell
python create_user.py add swapnil "Swapnil"
```
You'll be prompted to set a password (hidden input). Repeat for every end
user who needs access:
```powershell
python create_user.py add jane.doe "Jane Doe"
```
Manage accounts any time with:
```powershell
python create_user.py list
python create_user.py remove jane.doe
```

## 3. Run the app

From the `rcm_generator` folder:
```powershell
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```
- `--server.address 0.0.0.0` makes it reachable from other machines on your
  internal network, not just from the server itself.
- Leave this running (or set it up as a Windows service / scheduled task
  that starts it at boot, if you want it always available - ask if you'd
  like a script for that).

Anyone on the internal network can then open, in a normal browser:
```
http://<this-server's-IP-address-or-hostname>:8501
```
No SSH, RDP, or server login required - they'll see the sign-in page from
`auth.py`, log in with the account you created for them, and use the app.

## 4. Using the app (end-user side)

1. Sign in.
2. Upload walkthrough videos, supporting documents (SOPs/PPG/RBI
   directions/etc.), and optionally an existing RCM Excel file to use as the
   base.
3. Click **Generate RCM**. A spinner shows while it works - this runs the
   full pipeline (transcript step for any videos, then RCM generation across
   all 7 segments plus the gap-check QA pass), so it can take a while for a
   large upload, the same as running the scripts manually would.
4. Download the finished `.xlsx` when it's ready.

Each click uses a fresh, isolated working folder under `sessions/`, so two
people generating RCMs at the same time won't interfere with each other or
with your own manual `python main.py` runs in the main `source_docs/`
folder.

## Notes / limitations carried over from the existing pipeline

- Needs `ffmpeg`/`ffprobe` on the server (same requirement as
  `combined_video_transcript.py` already has).
- Needs the `small` (or whichever size you set up) model
  folder present, same as before - the app reuses
  `combined_video_transcript.WHISPER_MODEL_PATH`.
- Needs `config.py` filled in with a working Azure OpenAI key/endpoint/
  deployment, exactly as `main.py` already requires. The app checks this on
  load and shows a clear error banner instead of a blank crash if it isn't
  set.
- A run with several long videos and a large existing RCM can take a
  significant amount of time (the same amount it would take running
  `combined_video_transcript.py` then `main.py` by hand) - the browser tab
  needs to stay open with the spinner showing until it finishes.
