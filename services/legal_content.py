"""Static legal content for DPDPA compliance — Privacy Policy, ToS, disclosures."""

from db.config import settings

CURRENT_CONSENT_VERSION = "v1.0"


def get_privacy_policy() -> dict:
    """Returns structured privacy policy content compliant with DPDPA and IT Rules 2011."""
    grievance_name = getattr(settings, "GRIEVANCE_OFFICER_NAME", "") or "Privacy Officer"
    grievance_email = getattr(settings, "GRIEVANCE_OFFICER_EMAIL", "") or "privacy@legalaiexpert.in"

    return {
        "version": CURRENT_CONSENT_VERSION,
        "effective_date": "2026-04-13",
        "title": "Privacy Policy — Legal AI Expert",
        "sections": [
            {
                "heading": "1. Data We Collect",
                "content": (
                    "We collect the following categories of personal data:\n"
                    "- Account information: email address, name, firm details (for CAs)\n"
                    "- Financial documents: PDFs uploaded for compliance analysis (invoices, tax returns, notices, bank statements)\n"
                    "- Chat messages: queries and AI responses during document analysis\n"
                    "- Usage data: login timestamps, feature usage, IP addresses (for security)\n"
                    "- Payment information: processed securely via Razorpay (we do not store card details)"
                ),
            },
            {
                "heading": "2. How We Process Your Data",
                "content": (
                    "Your uploaded documents are processed using third-party AI services for compliance analysis:\n"
                    "- Google Gemini 2.5 Pro / Gemini 2.0 Flash: used for document extraction, compliance evaluation, "
                    "notice reply drafting, and financial analysis. Document text is sent to Google's Gemini API.\n"
                    "- OpenAI (text-embedding-3-small): used to create vector embeddings of document text for retrieval.\n\n"
                    "These services process your data under their respective enterprise data processing agreements. "
                    "Your data is NOT used for model training by Google or OpenAI under enterprise API terms.\n\n"
                    "We strongly recommend using our free PDF Redaction Tool to remove sensitive personal identifiers "
                    "(PAN, Aadhaar, names, addresses) from documents BEFORE uploading."
                ),
            },
            {
                "heading": "3. Third-Party Services",
                "content": (
                    "We share data with the following third parties solely for providing our services:\n"
                    "- Google Cloud (Gemini API): AI-powered document analysis\n"
                    "- OpenAI: Document embedding for search and retrieval\n"
                    "- Razorpay: Payment processing\n"
                    "- SendGrid (via SMTP): Email delivery for reports and notifications\n"
                    "- Google Cloud Platform: Infrastructure hosting (Cloud Run, Cloud SQL, GCS)"
                ),
            },
            {
                "heading": "4. Data Retention",
                "content": (
                    "- Uploaded documents and analysis results: retained until you delete them or exercise your right to erasure.\n"
                    "- Chat history: retained until you delete your data.\n"
                    "- Account information: retained as long as your account is active.\n"
                    "- Billing records (credit transactions): retained for 7 years as required by Indian tax law.\n"
                    "- Audit logs: retained for compliance and security purposes."
                ),
            },
            {
                "heading": "5. Your Rights Under DPDPA",
                "content": (
                    "Under India's Digital Personal Data Protection Act (DPDPA), 2023, you have the right to:\n"
                    "- Access: Request a copy of all personal data we hold about you (via Data Export in Settings).\n"
                    "- Erasure: Request deletion of all your personal data (via Delete My Data in Settings).\n"
                    "- Correction: Update your profile information at any time.\n"
                    "- Withdraw Consent: You may withdraw consent at any time; however, this will restrict access to AI-powered features.\n"
                    "- Grievance Redressal: Contact our Grievance Officer for any privacy concerns."
                ),
            },
            {
                "heading": "6. Data Security",
                "content": (
                    "We implement industry-standard security measures:\n"
                    "- All data in transit is encrypted via TLS/HTTPS.\n"
                    "- Passwords are hashed using bcrypt.\n"
                    "- JWT tokens expire after 7 days.\n"
                    "- Rate limiting on authentication endpoints (10 requests/minute).\n"
                    "- Per-user data isolation: each user's documents are stored in separate directories and vector databases."
                ),
            },
            {
                "heading": "7. Grievance Officer",
                "content": (
                    f"Name: {grievance_name}\n"
                    f"Email: {grievance_email}\n"
                    "Response time: Within 30 days of receiving your complaint, as mandated by DPDPA."
                ),
            },
        ],
    }


def get_terms_of_service() -> dict:
    """Returns structured Terms of Service content."""
    return {
        "version": CURRENT_CONSENT_VERSION,
        "effective_date": "2026-04-13",
        "title": "Terms of Service — Legal AI Expert",
        "sections": [
            {
                "heading": "1. Service Description",
                "content": (
                    "Legal AI Expert is an AI-powered compliance analysis platform for Chartered Accountants (CAs). "
                    "The platform provides document scanning, compliance auditing, GST reconciliation, bank statement analysis, "
                    "capital gains computation, depreciation scheduling, advance tax computation, and notice reply drafting."
                ),
            },
            {
                "heading": "2. AI-Generated Content Disclaimer",
                "content": (
                    "All analysis, reports, and recommendations generated by this platform are AI-assisted outputs. "
                    "They do NOT constitute legal, tax, or financial advice. All outputs must be reviewed and verified "
                    "by a qualified Chartered Accountant before filing or acting upon them. "
                    "Legal AI Expert and its operators bear no liability for decisions made based on AI-generated outputs."
                ),
            },
            {
                "heading": "3. Data Processing Consent",
                "content": (
                    "By using this service, you consent to:\n"
                    "- Processing of uploaded documents via Google Gemini AI and OpenAI APIs.\n"
                    "- Storage of document text in vector databases for retrieval-augmented generation.\n"
                    "- Use of your data solely for providing the contracted services.\n\n"
                    "You are responsible for ensuring you have the authority to upload client documents. "
                    "We recommend using our PDF Redaction Tool to remove personally identifiable information "
                    "(PAN, Aadhaar, names) before uploading."
                ),
            },
            {
                "heading": "4. Account and Credits",
                "content": (
                    "- Free trial: 75 credits. Credits are non-refundable and non-transferable.\n"
                    "- Paid plans: Starter (100 credits), Professional (300 credits), Enterprise (1000 credits).\n"
                    "- Credits are consumed per feature use (e.g., document scan: 3 credits, chat query: 1 credit).\n"
                    "- Subscriptions are managed via Razorpay."
                ),
            },
            {
                "heading": "5. Acceptable Use",
                "content": (
                    "You agree not to:\n"
                    "- Upload malicious files or attempt to compromise the platform.\n"
                    "- Use the service for fraudulent tax filing or evasion.\n"
                    "- Share your account credentials with unauthorized parties.\n"
                    "- Attempt to reverse-engineer or extract AI model weights."
                ),
            },
            {
                "heading": "6. Limitation of Liability",
                "content": (
                    "Legal AI Expert is provided 'as is'. We make no warranties regarding the accuracy, completeness, "
                    "or fitness for purpose of AI-generated outputs. Our total liability shall not exceed the fees "
                    "paid by you in the 12 months preceding the claim."
                ),
            },
            {
                "heading": "7. Governing Law",
                "content": (
                    "These terms are governed by the laws of India. Any disputes shall be subject to the exclusive "
                    "jurisdiction of the courts in Bengaluru, Karnataka."
                ),
            },
        ],
    }


def get_ai_processing_disclosure() -> dict:
    """Returns the AI processing disclosure text shown on upload pages."""
    return {
        "short": (
            "Your documents are processed using Google Gemini AI and OpenAI for analysis. "
            "Use our free PDF Redaction Tool to remove sensitive information before uploading."
        ),
        "detailed": (
            "By uploading documents, you acknowledge that:\n"
            "1. Document text is sent to Google Gemini 2.5 Pro/Flash API for extraction and analysis.\n"
            "2. Document text is sent to OpenAI for vector embedding (search indexing).\n"
            "3. Your data is NOT used for AI model training under enterprise API agreements.\n"
            "4. We strongly recommend redacting PAN, Aadhaar, and personal names before uploading."
        ),
        "redaction_tool_message": (
            "Protect your clients' sensitive data — download our free PDF Redaction Tool "
            "to permanently remove PAN, Aadhaar, bank account numbers, and personal names "
            "from documents before uploading. The tool uses the same technology used by "
            "law firms and government agencies for permanent document redaction."
        ),
    }
