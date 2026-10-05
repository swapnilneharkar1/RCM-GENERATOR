# RCM Generator (Micro Finance Loans)

Generates an enterprise-grade Risk Control Matrix from your SOPs, PPG, RBI
directions, and walkthrough evidence, using an LLM API (default: OpenAI
`gpt-5.4-mini` — change `MODEL_NAME` in `main.py` or set `OPENAI_MODEL` env
var if your account uses a different string for it).

## How it works

1. **`source_docs/`** — drop your documents here (`.pdf`, `.docx`, `.txt`, `.md`).
2. **`prompts/segments.py`** — the loan lifecycle is split into 7 segments
   (Origination, Branch Ops/Disbursement, Central Ops, Risk, RCU, Collections,
   Compliance) so each API call stays focused and produces genuinely
   thorough output instead of truncating.
3. **`document_loader.py`** — for each segment, filters `source_docs/` down
   to filename-relevant documents (keyword match) and builds a context block.
4. **`prompts/base_instructions.py`** — your original master prompt (role,
   4-step methodology, DE/OE lens, key-control criteria, output schema),
   parameterized per segment.
5. **`main.py`** — runs all 7 segments, concatenates rows, then runs one
   final **gap-check QA pass** against your quality checklist (maker-checker
   coverage, duplicates, fraud risk coverage, etc.).
6. **`excel_writer.py`** — writes everything to
   `output/RCM_MicroFinance_Loans.xlsx` with:
   - Sheet 1 "RCM": all 17 columns, filterable, gap rows highlighted amber,
     inferred-control rows highlighted green.
   - Sheet 2 "QA - Gap Check": the final QA pass results.

## Setup (Azure OpenAI)

This project connects to **Azure OpenAI Service**, not the direct OpenAI
platform - your key came from Azure, so the code uses Azure's client and
endpoint format.

```bash
cd rcm_generator
pip install -r requirements.txt
```

Open `config.py` and fill in:
- `AZURE_OPENAI_API_KEY` - your Azure resource key
- `AZURE_OPENAI_ENDPOINT` - just the base, e.g. `https://finance-openai.openai.azure.com/`
- `AZURE_OPENAI_API_VERSION` - e.g. `2025-04-01-preview`
- `AZURE_OPENAI_DEPLOYMENT` - your text deployment name, e.g. `gpt-5.4-mini`
- `AZURE_OPENAI_WHISPER_DEPLOYMENT` - only needed if you also have a Whisper
  deployment for video transcription (separate from the text deployment -
  ask your Azure admin if you don't have one yet)

**Before running anything else**, run the diagnostic:
```bash
python diagnose_connection.py
```
This confirms the text API call works (what `main.py` needs) and separately
reports whether the Whisper/audio call works (what `transcribe_videos.py`
needs) - these commonly succeed/fail independently since they're often
separate Azure deployments.

Drop your documents into `source_docs/`, e.g.:
```
source_docs/
  Micro_Finance_Loan_SOP.pdf
  Collections_SOP.pdf
  Loan_Cancellation_SOP.pdf
  Product_Program_Guide.pdf
  Detailed_Credit_Assessment_Program.pdf
  RBI_MFI_Directions.pdf
  branch_qc_walkthrough_transcript.txt
  disbursement_initiation_walkthrough_transcript.txt
  ...
```

Run:
```bash
python main.py
```

Output lands at `output/RCM_MicroFinance_Loans.xlsx`.

## Handling the videos (full walkthrough - `transcribe_videos.py`)

This project now includes `transcribe_videos.py`, which extracts audio from
your `.mp4`/`.webm` files and transcribes it via OpenAI's audio API,
producing a `.txt` file per video in `source_docs/` automatically.

**Important limitation:** this transcribes spoken narration only. If a video
is a silent screen recording with no one talking through it, the transcript
will be empty and this approach won't capture what's on screen (approvals
clicked, fields filled, etc.) - you'd need frame-extraction + a vision model
instead. Run the script and check for the "[NOTE] Transcript is empty"
warning it prints per video to find out which of your videos need that
different treatment.

### Setup (one-time)

1. **Get ffmpeg onto the server.** It's not a pip package - it's a
   standalone executable. On your internet-connected machine, download the
   "essentials" Windows build from https://www.gyan.dev/ffmpeg/builds/
   (a `.zip`), extract it, and copy `ffmpeg.exe` and `ffprobe.exe` from its
   `bin` folder into your `rcm_generator` project folder on the server (or
   anywhere, then set `FFMPEG_PATH`/`FFPROBE_PATH` at the top of
   `transcribe_videos.py` to the full path).

2. **`config.py` must already have your real API key** (same file `main.py`
   uses).

### Running it

```powershell
python transcribe_videos.py "C:\rcm_generator\RCM Files"
```

This scans that folder for video files, and for each one:
- extracts audio as mono 64kbps mp3 (small, fast, plenty for speech)
- splits into 10-minute chunks if the video is long (keeps each chunk under
  OpenAI's ~25MB transcription file size limit)
- transcribes each chunk via the `whisper-1` model
- writes `source_docs/<video_name>_transcript.txt`

This makes real API calls per chunk, so a handful of long videos will take
some minutes and consume some of your API quota. Run it once; you don't need
to re-run it unless a video changes.

Once transcripts exist in `source_docs/`, just run `python main.py` as usual
- it picks up `.txt` files automatically, same as any other document.


## Regenerating from an existing RCM

If you have a real, existing RCM as a `.xlsx` file, drop it into
`source_docs/` alongside your other documents. `main.py` detects it
automatically and treats it as **primary source material**:

- Each segment's existing rows (matched by Area/Process/Sub-Process against
  that segment's scope) get restructured, completed, and critically
  validated into the target 17-column schema - not just copied over.
  Vague/generic existing controls get flagged as weaknesses rather than
  silently polished. Risks with no existing row still get generated via the
  inference rule, clearly marked `[Inferred Control Based on Documentation]`.
- Large segments (200+ matching existing rows is normal for the "Loans"
  area of a big real RCM) are automatically split into multiple batched API
  calls (`RCM_ROWS_PER_BATCH` in `main.py`, default 40 rows/call) so no
  single call has to produce more output than it can safely fit - this
  means a full regeneration run makes considerably more API calls (~20-30
  instead of 7) and takes proportionally longer/costs more.
- Detected automatically by file extension - no flag or config needed, just
  have the `.xlsx` in `source_docs/`.
- The Excel parser auto-detects the header row (handles a title/logo above
  the real header) and maps columns by matching header text (e.g. "Control
  Description", "Risks Addressed", "Criticality") - it's tolerant of minor
  header wording differences across RCM templates, but if your file uses a
  very different structure, check `document_loader.py`'s `FIELD_HEADER_HINTS`
  list and add any missing header phrases there.
- Not detected as an RCM (silently skipped) if the sheet doesn't have
  recognizable Risk/Control Description columns - useful if you have other
  `.xlsx` files in `source_docs/` that aren't meant to be treated as an RCM.



- **More/fewer segments**: edit `prompts/segments.py`. If a segment's rows
  come back thin or truncated, split it into two smaller segments.
- **Document relevance matching is currently keyword-based** (filename
  contains e.g. "sop", "rbi", "collections"). For a larger document set,
  swap `document_loader.select_relevant_docs` for embeddings-based retrieval
  (e.g. `openai.embeddings` + cosine similarity) so relevance isn't limited
  to filename matching.
- **Cost/quality tradeoff**: `max_completion_tokens=8000` per segment call is
  a starting point — raise it if segments are truncating, lower it if you
  want tighter/cheaper runs.
- **Model swap**: any OpenAI-compatible chat completions endpoint works —
  just change `MODEL_NAME` / `OPENAI_API_KEY` / base URL if using a different
  provider (Azure OpenAI, local vLLM, etc. — set `OpenAI(base_url=...)` in
  `main.py`).
