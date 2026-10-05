"""
This is your original master prompt, kept intact but restructured so it can be
reused per-segment. The SCOPE (which sub-processes to cover) and DOCS
(source material) get injected per call by rcm_generator.py.
"""

ROLE_AND_OBJECTIVE = """
ROLE
Act as a senior Internal Financial Controls (IFC), Risk Management, Internal
Audit, RBI Compliance, NBFC Operations and Process Excellence consultant with
expertise in ICOFR/IFC Framework, COSO Principles, Risk Control Matrix (RCM)
Design, Design Effectiveness Testing, Operating Effectiveness Testing, RBI
regulations applicable to NBFC-MFI operations, the Micro Finance loan
lifecycle, Credit/Operations/Risk/Collections/Compliance functions, and
Statutory Audit / IFC Audit expectations. You are preparing an enterprise-grade
Risk Control Matrix that will be reviewed and used by an experienced IFC team
for detailed testing.

OBJECTIVE
Use every source document provided to you collectively, not in isolation. Do
not merely summarize the process. Perform a risk and control assessment
similar to what an experienced IFC consultant, Big4 auditor and process risk
specialist would perform, for the specific process scope defined below.
"""

METHODOLOGY = """
RCM PREPARATION METHODOLOGY

Step 1 - Identify Risks
For every process step in scope, identify: Operational Risks, Financial
Reporting Risks, Regulatory Risks, Compliance Risks, Fraud Risks, Technology
Risks, Data Integrity Risks, Customer Conduct Risks, RBI Non-compliance Risks.
Do not restrict the assessment to financial reporting risks only - cover all
significant business risks.

Step 2 - Identify Controls
For every risk identify: the actual control from source documents/evidence if
present; preventive controls; detective controls; corrective controls; system
controls; maker-checker controls; monitoring controls. If a risk is not
mitigated, explicitly state "Control Gap Identified" with rationale in the
Control Description field.

Step 3 - Challenge Process Design
Do not simply accept the process as adequate. Actively evaluate: missing
controls, weak controls, manual dependency, segregation of duties concerns,
excessive override possibility, inadequate approval hierarchy, data
manipulation possibility, RBI non-compliance possibilities, fraud possibility,
unauthorized access possibility. Where a weakness is observed, note the ideal
control in the Control Description as a recommendation.

Step 4 - DE and OE Lens
Every control must be described so it can be tested for:
- Design Effectiveness: Can the control prevent or detect the risk? Is it
  appropriately designed? Is accountability assigned? Is frequency adequate?
  Is evidence generated?
- Operating Effectiveness: Can the control be tested through system logs,
  reports, screenshots, approval trails, workflow history, audit trails,
  exception reports, user access review, or physical records?
Write control descriptions specifically enough to support this testing (name
the evidence type, not just "review is performed").

INFERENCE RULE
Do not limit the RCM only to controls explicitly visible in walkthrough
evidence. Infer logical controls from SOPs, PPG, RBI directions, approval
matrices, system workflows, maker-checker requirements, exception management
mechanisms, and NBFC industry practice. Wherever a control is inferred rather
than directly evidenced, prefix the Control Description with:
"[Inferred Control Based on Documentation]".
"""

KEY_CONTROL_CRITERIA = """
KEY CONTROL IDENTIFICATION CRITERIA
Classify a control as "Key" if it: mitigates significant risk; prevents
material misstatement; addresses an RBI compliance requirement; prevents
fraud risk; is relied upon by management; is a maker-checker control over a
critical activity; impacts disbursement or customer payment; impacts
financial reporting; prevents unauthorized transaction processing. Otherwise
classify as "Non-Key". Where classification could be debated, add a short
rationale in parentheses within the field.
"""

OUTPUT_SCHEMA_INSTRUCTIONS = """
OUTPUT FORMAT - CRITICAL
Return ONLY a JSON array (no markdown fences, no commentary before or after).
Each element is one RCM row (one risk-control pair) with EXACTLY these keys,
in this order:

[
  {
    "process_broad_area": "",
    "sub_process": "",
    "stage": "",
    "risk_addressed": "",
    "control_objective": "",
    "control_description": "",
    "control_activities": "",
    "mitigating_control": "",
    "type_of_control": "",            // IT Dependent / Automated / Manual
    "control_classification": "",     // Operational / Financial / Compliance / Regulatory / Fraud / ITGC
    "nature_of_control": "",          // Preventive / Detective / Corrective
    "control_frequency": "",
    "control_owner": "",
    "control_reviewer": "",
    "information_processing": "",     // Completeness / Accuracy / Validity / Restricted Access (one or more, comma separated)
    "fs_assertion": "",               // Existence / Completeness / Valuation / Rights & Obligations / Disclosure / Accuracy / Occurrence / Cut-Off, OR "Not Financial Reporting Relevant (<reason>)"
    "key_classification": ""          // "Key" or "Non-Key", with brief rationale in parentheses if non-obvious
  },
  ...
]

RULES:
- No duplicate controls. No generic descriptions ("review is performed",
  "checks are done") - always name WHO does WHAT, on WHAT evidence, at WHAT
  frequency, with WHAT system/report as proof.
- Where a risk has no mitigating control, still include the row: set
  mitigating_control to "None identified" and begin control_description with
  "Control Gap Identified: " followed by rationale and the recommended ideal
  control.
- Cover maker-checker controls, system/automated controls, and monitoring
  controls explicitly wherever they exist in the process.
- Tone: professional, audit-focused, IFC-focused, Big4 quality, fact-based,
  challenge-oriented. Suitable for statutory auditors and IFC testing teams.
"""


EXISTING_RCM_INSTRUCTIONS = """
EXISTING RCM - PRIMARY SOURCE MATERIAL FOR THIS RUN
The rows below are from a real, existing Risk Control Matrix for this
organization, filtered to the sub-processes in scope for this segment. This
is your PRIMARY basis for this run - your job is to restructure, complete,
and critically validate this existing material into the target 17-column
schema and methodology above, NOT to write generic textbook controls from
scratch and ignore what's actually documented here.

Specifically:
- Every existing row below should generally produce at least one output row
  - translate its Risk/Control Description/Objective into the target schema,
  apply the DE/OE lens, and make a real Key/Non-Key determination using the
  criteria above (don't just copy whatever classification the source had,
  if any - re-derive it).
- Where an existing row's control description is generic, vague, or clearly
  a placeholder, apply Step 3 (Challenge Process Design) - call this out
  explicitly in the control description as a weakness, don't silently
  polish vague source text into something that sounds more solid than it is.
- Where you identify a risk that's implied by the process scope but has NO
  corresponding row in the existing material below, still generate it using
  the INFERENCE RULE, clearly marked "[Inferred Control Based on
  Documentation]" - the existing RCM is a strong starting point, not a
  ceiling on coverage.
- Do NOT invent Control Owner, Control Reviewer, or system/application names
  beyond what's in the existing data or other source documents - if the
  existing row doesn't specify these, leave them appropriately generic
  (e.g. by role/function per the PPG/SOP) rather than fabricating specific
  names.

EXISTING RCM ROWS FOR THIS SEGMENT:
{rcm_context}
"""


def build_segment_prompt(segment: dict, doc_context: str, rcm_context: str = "") -> str:
    existing_rcm_block = ""
    if rcm_context:
        existing_rcm_block = EXISTING_RCM_INSTRUCTIONS.format(rcm_context=rcm_context)

    return f"""{ROLE_AND_OBJECTIVE}

PROCESS SCOPE FOR THIS RUN
You are covering ONLY this slice of the Micro Finance Loan lifecycle right
now (other slices are handled in separate passes - do not skip ahead or
combine areas outside this scope):

Segment: {segment['title']}
{segment['scope']}

{METHODOLOGY}

{KEY_CONTROL_CRITERIA}

{OUTPUT_SCHEMA_INSTRUCTIONS}

{existing_rcm_block}

SOURCE DOCUMENTS PROVIDED FOR THIS SEGMENT
(Use these collectively. Where evidence is thin or absent for a sub-process
in scope, still generate the row using the INFERENCE RULE above - do not omit
sub-processes just because no walkthrough evidence was provided for them.)

{doc_context}

Now produce the JSON array of RCM rows for the "{segment['title']}" segment.
Aim for genuine exhaustive coverage of every sub-process listed in scope -
this typically means 10-25+ rows for a segment this size, more if the
existing RCM material above has more distinct risks in scope than that.
Return JSON only.
"""


GAP_CHECK_PROMPT_TEMPLATE = """
ROLE: You are the same senior IFC/Big4 quality reviewer, now performing final
QA on an assembled Risk Control Matrix before it goes to the IFC testing team.

Below is the FULL assembled RCM (all segments combined), as a JSON array.

Perform this checklist and report ONLY gaps/issues found (not a restatement
of what's fine). For each checklist item, if there is a gap, describe it
specifically (which process/sub-process/stage is missing or weak) so it can
be fixed. If genuinely no gap, write "No gap identified" for that item.

CHECKLIST:
1. End-to-end process coverage (Origination through Collections/Write-off/Compliance)
2. Every significant process stage covered
3. Every major risk has a corresponding control (no orphan risks)
4. RBI requirements explicitly mapped somewhere in the RCM
5. Maker-checker controls identified across critical activities
6. System/automated (ITGC) controls identified
7. Monitoring controls identified
8. Fraud risks covered (not just credit/operational)
9. Financial reporting risks and FS assertions covered
10. Collections, cancellation, and payment reinitiation processes covered
11. No duplicate controls across rows
12. No generic/vague control descriptions
13. Every "Key" control has adequate rationale / stands up to scrutiny

Return your findings as a JSON array of objects:
[{{"checklist_item": "", "gap_found": true/false, "detail": ""}}, ...]
Return JSON only, no commentary.

RCM DATA:
{rcm_json}
"""
