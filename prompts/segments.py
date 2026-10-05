"""
The full RCM master prompt is split into LIFECYCLE SEGMENTS.

Why segments instead of one giant call:
- A single call covering all 9 process areas x 17 columns x 100+ rows either
  gets truncated by max_tokens or produces shallow/generic rows because the
  model is trying to cover too much ground at once.
- Each segment gets the FULL instruction set (role, DE/OE lens, output format,
  key-control criteria, quality checklist) but is scoped to a specific slice
  of the loan lifecycle, plus only the source documents relevant to that slice.
- This keeps the model's attention concentrated and lets each segment run
  long enough to be genuinely thorough (challenge weak controls, infer
  controls from SOP/PPG/RBI where walkthrough evidence is silent, etc).

Each segment below defines:
- key: internal id
- title: human label
- scope: the specific sub-processes this segment must cover (from your prompt)
- doc_hints: filename keywords to prioritize when assembling context for this
  segment (used by document_loader.select_relevant_docs)
"""

SEGMENTS = [
    {
        "key": "origination",
        "title": "Loan Origination & Customer Acquisition",
        "scope": """
- Customer Identification, Group Formation, Customer Acquisition, Lead Generation
- Loan Application, KYC Collection, KYC Verification, Bureau Check
- Income Assessment, Eligibility Assessment, Repayment Capacity Assessment
- Credit Scoring, Field Verification, Documentation
""",
        "doc_hints": ["sop", "micro finance", "ppg", "product program", "sourcing", "kyc", "credit assessment"],
    },
    {
        "key": "branch_ops",
        "title": "Branch Operations, Underwriting & Disbursement",
        "scope": """
- Branch Operations, Sourcing, Maker Activities, Checker Review, Quality Check
- Underwriting Review, Approval Mechanism, Exception Handling
- Disbursement Initiation, Account Validation, Bank Verification, Sanction
  Validation, Disbursement Approval, Fund Transfer, Accounting Entry Generation
""",
        "doc_hints": ["branch operations", "quality check", "qc", "disbursement", "sourcing", "sop", "branch ops"],
    },
    {
        "key": "central_ops",
        "title": "Central Operations",
        "scope": """
- Loan Cancellation, Payment Reinitiation, Customer Refund
- Reversal Processing, Adjustments
""",
        "doc_hints": ["central operations", "loan cancellation", "payment reinitiation", "central ops", "sop"],
    },
    {
        "key": "risk",
        "title": "Risk Function",
        "scope": """
- Credit Appraisal, Portfolio Monitoring, Policy Monitoring, Risk Reporting
- Delinquency Monitoring, Branch Risk Identification
""",
        "doc_hints": ["risk policy", "credit appraisal", "branch identification", "portfolio review", "risk"],
    },
    {
        "key": "rcu",
        "title": "RCU (Fraud) Function",
        "scope": """
- Fraud Detection, Fraud Investigation, Verification Controls
- Field Validation, High Risk Case Review
""",
        "doc_hints": ["rcu", "fraud", "verification"],
    },
    {
        "key": "collections",
        "title": "Collections",
        "scope": """
- Collection Allocation, Receipt Processing, Cash Controls, Collection Monitoring
- Delinquency Management, NPA Monitoring, Write Off Process, Recovery Process
""",
        "doc_hints": ["collections", "receipt", "npa", "write off", "recovery"],
    },
    {
        "key": "compliance",
        "title": "Regulatory Compliance (RBI / Fair Practice Code)",
        "scope": """
- RBI MFI Directions, Fair Practice Code, Customer Consent, Customer
  Communication, Regulatory Reporting, Customer Protection Requirements,
  Interest Rate Compliance, Lending Norm Compliance
""",
        "doc_hints": ["rbi", "direction", "fair practice", "compliance", "consent", "interest rate"],
    },
]

# Segment run LAST, over the assembled output of all the above.
GAP_CHECK_KEY = "gap_check"
