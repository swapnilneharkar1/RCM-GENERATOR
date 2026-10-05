"""
RCM Generator - main entry point.

Usage:
    python main.py

What it does:
    1. Loads every document from ./source_docs/ (SOPs, PPG, RBI directions,
       video transcripts, etc.)
    2. ALSO loads any .xlsx file(s) in ./source_docs/ as an EXISTING RCM
       reference - if present, this becomes the PRIMARY source material:
       each segment restructures/completes/validates the matching existing
       rows into the target 17-column schema, rather than generating from
       scratch. Large segments (200+ matching existing rows) are
       automatically split into multiple batched API calls so no single
       call has to produce more output than it safely can.
    3. For each lifecycle segment (prompts/segments.py), builds a focused
       prompt (role + methodology + scope + relevant docs + relevant
       existing-RCM rows) and calls the model, expecting a JSON array of
       RCM rows back.
    4. Concatenates all rows from all segments/batches.
    5. Runs a final "gap check" QA pass against your quality checklist.
    6. Writes everything to ./output/RCM_MicroFinance_Loans.xlsx

Model:
    Deployment/endpoint/key come from config.py (Azure OpenAI).

Notes on reliability:
    - LLMs occasionally wrap JSON in markdown fences or add stray text
      despite instructions. `extract_json` strips this defensively.
    - Each API call is retried once on JSON-parse failure before giving up
      on that call (so one bad batch doesn't kill the whole run).
    - Batching (RCM_ROWS_PER_BATCH) exists specifically so segments with a
      lot of matching existing-RCM rows don't silently truncate output -
      lower it if you still see truncation, raise it to reduce total API
      call count if your model handles longer outputs reliably.
"""

import os
import re
import json
import sys
from pathlib import Path

from openai import AzureOpenAI

from document_loader import (
    load_all_documents, select_relevant_docs,
    load_all_rcm_excels, filter_relevant_rcm_rows, format_rcm_rows_as_text,
)
from prompts.segments import SEGMENTS
from prompts.base_instructions import build_segment_prompt, GAP_CHECK_PROMPT_TEMPLATE
from excel_writer import write_rcm_workbook
import config

BASE_DIR = Path(__file__).parent
SOURCE_DOCS_DIR = BASE_DIR / "source_docs"
OUTPUT_PATH = BASE_DIR / "output" / "RCM_MicroFinance_Loans.xlsx"

API_KEY = getattr(config, "AZURE_OPENAI_API_KEY", "")
ENDPOINT = getattr(config, "AZURE_OPENAI_ENDPOINT", "")
API_VERSION = getattr(config, "AZURE_OPENAI_API_VERSION", "")
DEPLOYMENT = getattr(config, "AZURE_OPENAI_DEPLOYMENT", "")

client = AzureOpenAI(
    api_key=API_KEY,
    azure_endpoint=ENDPOINT,
    api_version=API_VERSION,
)


def extract_json(raw_text: str):
    """Defensively strip markdown fences / stray text and parse JSON."""
    text = raw_text.strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    # If there's still leading/trailing junk, grab the outermost [ ... ] or { ... }
    match = re.search(r"(\[.*\]|\{.*\})", text, re.DOTALL)
    if match:
        text = match.group(1)
    return json.loads(text)


def call_model(prompt: str, max_tokens: int = 8000) -> str:
    """
    Uses Azure's Responses API (matches the /openai/responses endpoint your
    deployment provides). Falls back to parsing response.output manually if
    the installed SDK version doesn't have the .output_text convenience
    property.
    """
    response = client.responses.create(
        model=DEPLOYMENT,
        input=prompt,
        max_output_tokens=max_tokens,
    )
    text = getattr(response, "output_text", None)
    if text:
        return text
    # Fallback manual extraction
    chunks = []
    for item in getattr(response, "output", []) or []:
        if getattr(item, "type", None) == "message":
            for content in getattr(item, "content", []) or []:
                if getattr(content, "type", None) in ("output_text", "text"):
                    chunks.append(getattr(content, "text", ""))
    return "\n".join(chunks)


RCM_ROWS_PER_BATCH = 40  # existing-RCM rows per API call when regenerating
                          # from an existing RCM - keeps output well within
                          # token budget (~40 existing rows -> comfortably
                          # under max_output_tokens even accounting for the
                          # model potentially splitting some into multiple
                          # risk/control pairs).


def call_segment_once(prompt: str, label: str) -> list:
    """One API call + parse + retry-on-failure + diagnostics for empty
    results. Shared by both the no-existing-RCM path and each batch of the
    existing-RCM path."""
    for attempt in range(2):
        raw_response_obj = None
        try:
            response = client.responses.create(
                model=DEPLOYMENT,
                input=prompt,
                max_output_tokens=12000,
            )
            raw_response_obj = response
            raw = getattr(response, "output_text", None)
            if not raw:
                chunks = []
                for item in getattr(response, "output", []) or []:
                    if getattr(item, "type", None) == "message":
                        for content in getattr(item, "content", []) or []:
                            if getattr(content, "type", None) in ("output_text", "text"):
                                chunks.append(getattr(content, "text", ""))
                raw = "\n".join(chunks)

            rows = extract_json(raw) if raw else []
            if not isinstance(rows, list):
                raise ValueError("Expected a JSON array of rows")

            if len(rows) == 0:
                print(f"     [WARNING] {label}: 0 rows returned with no JSON error. Diagnosing...")
                status = getattr(raw_response_obj, "status", None)
                print(f"     Response status: {status}")
                incomplete = getattr(raw_response_obj, "incomplete_details", None)
                if incomplete:
                    print(f"     Incomplete details: {incomplete}")
                for item in getattr(raw_response_obj, "output", []) or []:
                    item_type = getattr(item, "type", None)
                    if item_type == "message":
                        for content in getattr(item, "content", []) or []:
                            if getattr(content, "type", None) == "refusal":
                                print(f"       REFUSAL TEXT: {getattr(content, 'refusal', '')}")
                print(f"     Raw output (first 300 chars): {raw[:300] if raw else '(empty)'}")
                if attempt == 0:
                    print(f"     Retrying...")
                    continue

            print(f"     {label}: {len(rows)} rows generated")
            return rows
        except (json.JSONDecodeError, ValueError) as e:
            print(f"     [attempt {attempt + 1}] {label}: JSON parse failed ({e}), "
                  f"{'retrying' if attempt == 0 else 'giving up on this batch'}")
    return []


def run_segment(segment: dict, all_docs: dict, rcm_rows: list) -> list:
    print(f"  -> Segment: {segment['title']}")
    doc_context = select_relevant_docs(all_docs, segment["doc_hints"])
    matched_rcm_rows = filter_relevant_rcm_rows(rcm_rows, segment["doc_hints"]) if rcm_rows else []

    if not matched_rcm_rows:
        # No existing-RCM material for this segment - single call, same as
        # the original document/inference-only path.
        prompt = build_segment_prompt(segment, doc_context, "")
        return call_segment_once(prompt, "single call")

    # Batch the existing-RCM rows so no single call has to restructure more
    # material than it can realistically produce in one response.
    num_batches = (len(matched_rcm_rows) + RCM_ROWS_PER_BATCH - 1) // RCM_ROWS_PER_BATCH
    print(f"     {len(matched_rcm_rows)} existing RCM row(s) matched - "
          f"processing in {num_batches} batch(es) of up to {RCM_ROWS_PER_BATCH}")

    all_rows = []
    for b in range(num_batches):
        batch = matched_rcm_rows[b * RCM_ROWS_PER_BATCH:(b + 1) * RCM_ROWS_PER_BATCH]
        rcm_context = format_rcm_rows_as_text(batch)
        prompt = build_segment_prompt(segment, doc_context, rcm_context)
        rows = call_segment_once(prompt, f"batch {b+1}/{num_batches}")
        all_rows.extend(rows)
    return all_rows


def run_gap_check(all_rows: list) -> list:
    print("  -> Running final gap-check QA pass")
    # Trim the payload sent back for QA to keep it manageable - send key
    # fields only, not full descriptions, if the RCM is very large.
    # NOTE: when regenerating from a large existing RCM (600+ rows is
    # normal for a real enterprise RCM), this payload can reach ~50-60K
    # input tokens even slimmed down. That's fine for a 128K+ context
    # model but if you hit a context-length error here, either drop more
    # fields below (e.g. control_classification) or split the gap-check
    # into per-area calls instead of one call across everything.
    slim_rows = [
        {
            "process_broad_area": r.get("process_broad_area"),
            "sub_process": r.get("sub_process"),
            "stage": r.get("stage"),
            "risk_addressed": r.get("risk_addressed"),
            "mitigating_control": r.get("mitigating_control"),
            "control_classification": r.get("control_classification"),
            "key_classification": r.get("key_classification"),
        }
        for r in all_rows
    ]
    prompt = GAP_CHECK_PROMPT_TEMPLATE.format(rcm_json=json.dumps(slim_rows, indent=1))
    raw = call_model(prompt, max_tokens=4000)
    try:
        return extract_json(raw)
    except (json.JSONDecodeError, ValueError):
        print("     [warning] gap-check JSON parse failed, skipping QA sheet content")
        return []


def main():
    if not API_KEY or "PASTE-YOUR-AZURE-KEY-HERE" in API_KEY:
        print("ERROR: No Azure API key found. Paste it into config.py "
              "(AZURE_OPENAI_API_KEY = \"...\") before running.")
        sys.exit(1)
    if not ENDPOINT:
        print("ERROR: AZURE_OPENAI_ENDPOINT is not set in config.py.")
        sys.exit(1)

    print(f"Loading source documents from {SOURCE_DOCS_DIR} ...")
    all_docs = load_all_documents(str(SOURCE_DOCS_DIR))
    if not all_docs:
        print(f"  [warning] No documents found in {SOURCE_DOCS_DIR}. "
              f"Segments will rely entirely on inference from general "
              f"NBFC-MFI/RBI knowledge - drop your SOPs/PPG/RBI directions/"
              f"transcripts in there for a much stronger RCM.")
    else:
        print(f"  Loaded {len(all_docs)} document(s): {', '.join(all_docs.keys())}")

    rcm_rows = load_all_rcm_excels(str(SOURCE_DOCS_DIR))
    if rcm_rows:
        print(f"  Loaded {len(rcm_rows)} existing RCM row(s) from .xlsx file(s) in "
              f"source_docs - these will be used as PRIMARY source material, "
              f"restructured/completed/validated into the target 17-column schema.")
    else:
        print(f"  No existing RCM .xlsx found in source_docs - generating from "
              f"documents/inference only (normal if you're not regenerating from "
              f"an existing RCM).")

    print(f"\nGenerating RCM using deployment '{DEPLOYMENT}' across {len(SEGMENTS)} segments...")
    all_rows = []
    for segment in SEGMENTS:
        rows = run_segment(segment, all_docs, rcm_rows)
        all_rows.extend(rows)

    print(f"\nTotal RCM rows generated: {len(all_rows)}")

    gap_findings = run_gap_check(all_rows) if all_rows else []

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    write_rcm_workbook(all_rows, gap_findings, str(OUTPUT_PATH))
    print(f"\nDone. Workbook written to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
