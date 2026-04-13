"""Static content: what to redact vs. keep when preparing documents for Legal AI Expert."""

GUIDE_TITLE = "PDF Redaction Guide"

WHAT_TO_REDACT = [
    ("PAN Numbers", "e.g., ABCDE1234F — 5 letters + 4 digits + 1 letter"),
    ("Aadhaar Numbers", "12-digit unique identity numbers"),
    ("Personal Names", "Names of individuals (not company/firm names)"),
    ("Bank Account Numbers", "Savings/current account numbers"),
    ("Signatures", "Digital or scanned signatures"),
    ("Personal Addresses", "Residential addresses of individuals"),
    ("Phone Numbers", "Personal mobile/landline numbers"),
]

WHAT_NOT_TO_REDACT = [
    ("GSTIN", "Needed for GST reconciliation and compliance checks"),
    ("Dates", "All dates are needed for analysis — filing dates, invoice dates, assessment years"),
    ("Amounts & Figures", "Tax amounts, invoice values, interest — critical for all analysis"),
    ("Invoice Numbers", "Required for matching in GST reconciliation"),
    ("Assessment Year / FY", "Needed to determine applicable rules and deadlines"),
    ("Tax Computation Details", "Deductions, exemptions, taxable income — needed for analysis"),
    ("Company/Firm Names", "Required for compliance identification"),
    ("Section/Rule References", "Legal references needed for compliance evaluation"),
]

GUIDE_HTML = f"""
<h2>{GUIDE_TITLE}</h2>
<p>Use this tool to permanently remove sensitive personal information from PDFs
before uploading to Legal AI Expert. This ensures your clients' PII never reaches
third-party AI services.</p>

<h3 style="color: #d32f2f;">What to REDACT (draw black boxes over these):</h3>
<ul>
{"".join(f'<li><b>{item}</b> — {desc}</li>' for item, desc in WHAT_TO_REDACT)}
</ul>

<h3 style="color: #2e7d32;">What NOT to redact (keep these visible):</h3>
<ul>
{"".join(f'<li><b>{item}</b> — {desc}</li>' for item, desc in WHAT_NOT_TO_REDACT)}
</ul>

<p><b>Important:</b> Redaction is <b>permanent</b>. Once applied, the underlying text is
completely removed from the PDF — it cannot be recovered even by removing the black boxes.
Always save the redacted version as a separate file.</p>
"""
