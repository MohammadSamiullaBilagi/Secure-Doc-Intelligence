"""Static legal content for DPDPA compliance — Privacy Policy, ToS, disclosures.

Shape of privacy/ToS responses:
    {
        "version": "v1.1",
        "effective_date": "YYYY-MM-DD",
        "title": str,
        "sections": [{"heading": str, "content": str (markdown)}, ...]
    }

Sections use markdown so the frontend can render with react-markdown.
Bumped to v1.1 on 2026-04-14 to expand all sections with compliance-grade
content covering DPDPA 2023 §§ 5–11, IT Rules 2011 Rule 4, retention periods,
international transfers, grievance redressal, breach notification, children's
data, cookies, and AI-output disclaimers. Bumping the version forces existing
users to re-accept the expanded terms via the dashboard consent banner.
"""

from db.config import settings

CURRENT_CONSENT_VERSION = "v1.1"
EFFECTIVE_DATE = "2026-04-14"


def _grievance_officer() -> tuple[str, str]:
    name = getattr(settings, "GRIEVANCE_OFFICER_NAME", "") or "Grievance Officer, Legal AI Expert"
    email = getattr(settings, "GRIEVANCE_OFFICER_EMAIL", "") or "privacy@legalaiexpert.in"
    return name, email


def get_privacy_policy() -> dict:
    """Returns structured privacy policy content compliant with DPDPA 2023 and IT Rules 2011.

    Each section is markdown-formatted so the frontend can render with
    react-markdown. Headings and section order are stable — downstream
    consumers (sidebar TOC, anchors) can rely on them.
    """
    grievance_name, grievance_email = _grievance_officer()

    return {
        "version": CURRENT_CONSENT_VERSION,
        "effective_date": EFFECTIVE_DATE,
        "last_updated": EFFECTIVE_DATE,
        "title": "Privacy Policy — Legal AI Expert",
        "sections": [
            {
                "heading": "1. Introduction & Scope",
                "content": (
                    "Legal AI Expert (\"**we**\", \"**us**\", \"**our**\", or \"**the Platform**\") "
                    "is an AI-assisted compliance analysis service operated for Chartered Accountants "
                    "(\"**CAs**\") and tax professionals in India. This Privacy Policy explains what "
                    "personal data we collect, how we use it, who we share it with, how long we retain "
                    "it, and the rights you have as a Data Principal under India's Digital Personal "
                    "Data Protection Act, 2023 (\"**DPDPA**\") and the Information Technology "
                    "(Reasonable Security Practices and Procedures and Sensitive Personal Data or "
                    "Information) Rules, 2011 (\"**IT Rules 2011**\").\n\n"
                    "This Policy applies to:\n\n"
                    "- The web application hosted at `https://legalaiexpert.in` and any sub-domains\n"
                    "- The REST API at `/api/v1/*`\n"
                    "- The standalone **PDF Redaction Tool** desktop application\n"
                    "- Any communications (email, SMS, in-app notifications) sent from or on behalf of the Platform\n\n"
                    "By creating an account, uploading a document, or otherwise using the Platform, "
                    "you acknowledge that you have read and understood this Policy. If you do not "
                    "agree, you must not use the Platform. Where you upload documents belonging to "
                    "your clients in a professional capacity, you represent that you have obtained "
                    "all necessary authorisations from those clients and are acting lawfully as a "
                    "Data Fiduciary with respect to their data under DPDPA."
                ),
            },
            {
                "heading": "2. Data Fiduciary Identity & Grievance Officer",
                "content": (
                    "For the purposes of DPDPA §§ 2(i) and 10, the **Data Fiduciary** is the "
                    "operator of Legal AI Expert. The Data Fiduciary determines the purpose and "
                    "means of processing the personal data you submit to the Platform.\n\n"
                    "**Grievance Officer (DPDPA § 8(10) & IT Rules 2011 Rule 5(9))**\n\n"
                    f"- **Name:** {grievance_name}\n"
                    f"- **Email:** {grievance_email}\n"
                    "- **Response window:** Acknowledgement within 72 hours; substantive response "
                    "within 30 days of receiving the grievance, as mandated by DPDPA.\n"
                    "- **Escalation:** If you are not satisfied with the Grievance Officer's "
                    "response, you may escalate to the Data Protection Board of India once it is "
                    "operationalised, or approach an appropriate court of competent jurisdiction "
                    "in Bengaluru, Karnataka.\n\n"
                    "You may contact the Grievance Officer at any time to exercise any of the "
                    "rights described in Section 7 below, to raise a concern about how your data "
                    "is being processed, or to report a suspected breach."
                ),
            },
            {
                "heading": "3. Categories of Personal Data We Collect",
                "content": (
                    "We collect and process the following categories of personal data:\n\n"
                    "**(a) Account & Profile Data**\n"
                    "- Full name, email address, password hash (bcrypt — we never store plaintext passwords)\n"
                    "- CA firm name, membership number, preferred email for client communications\n"
                    "- Phone number (optional, for account recovery and reminders)\n"
                    "- Subscription plan, credit balance, billing history\n\n"
                    "**(b) Documents You Upload** *(may contain SPDI as defined in IT Rules 2011 Rule 3)*\n"
                    "- Tax returns, GST returns (GSTR-1/3B/9), invoices, purchase registers\n"
                    "- Bank statements (account numbers, counterparties, transaction amounts)\n"
                    "- Notices and assessment orders (may contain PAN, TAN, GSTIN)\n"
                    "- Supporting documents for capital gains, depreciation, advance tax\n"
                    "- Any identifiers present in the documents (PAN, Aadhaar, bank account numbers, signatures)\n\n"
                    "**(c) Derived & Analytical Data**\n"
                    "- Extracted fields (e.g., taxable value, tax paid, due dates)\n"
                    "- AI-generated analysis, reports, flags, reconciliation results\n"
                    "- Vector embeddings of document text stored in per-user ChromaDB collections\n"
                    "- Chat history between you and the AI assistant (persisted for conversation memory)\n\n"
                    "**(d) Usage & Telemetry Data**\n"
                    "- Login timestamps, IP addresses, User-Agent strings\n"
                    "- Audit logs of sensitive actions (login, document upload, data export, data deletion, consent updates)\n"
                    "- Feature usage counters (credit consumption per feature)\n\n"
                    "**(e) Payment Data**\n"
                    "- We **do not** store card numbers, CVV, or bank login credentials. Payment is handled "
                    "end-to-end by Razorpay, which is PCI-DSS compliant.\n"
                    "- We store only the Razorpay order ID, payment ID, amount, currency, status, and timestamp.\n\n"
                    "**Sensitive Personal Data or Information (SPDI)** — uploaded documents may contain "
                    "SPDI such as financial information and passwords. You consent to our processing of "
                    "such SPDI solely for the purposes listed in Section 4. We urge you to use our free "
                    "**PDF Redaction Tool** to permanently remove PAN, Aadhaar, names, and bank account "
                    "numbers **before** uploading — see the AI Processing Disclosure for details."
                ),
            },
            {
                "heading": "4. Purposes of Processing & Legal Basis",
                "content": (
                    "We process your personal data only for the specific purposes listed below. "
                    "Our legal basis is your **consent** under DPDPA § 6, captured at registration "
                    "and re-confirmed whenever this Policy is materially updated, and **performance "
                    "of contract** under DPDPA § 7(a) for subscription-related processing.\n\n"
                    "| Purpose | Legal Basis | Data Used |\n"
                    "|---|---|---|\n"
                    "| Account creation & authentication | Contract | Account data |\n"
                    "| AI-assisted document analysis (audits, GST recon, bank analysis, etc.) | Consent | Documents, derived data |\n"
                    "| Chat assistance with conversation memory | Consent | Chat history, document context |\n"
                    "| Compliance report generation & email delivery | Consent | Derived data, email |\n"
                    "| Subscription billing & credit management | Contract | Account data, payment data |\n"
                    "| Security monitoring & fraud prevention | Legitimate use (DPDPA § 7(i)) | Usage telemetry, audit logs |\n"
                    "| Grievance handling & legal compliance | Legal obligation (DPDPA § 7(b)) | Any relevant data |\n"
                    "| Product improvement (aggregated, non-identifying) | Consent | Anonymised usage metrics only |\n\n"
                    "**We do NOT:**\n"
                    "- Sell your personal data to any third party\n"
                    "- Use your documents to train our own AI models\n"
                    "- Share your data with advertisers or data brokers\n"
                    "- Profile you for targeted advertising\n"
                    "- Make solely-automated decisions with legal or similarly significant effects without human review"
                ),
            },
            {
                "heading": "5. Third-Party Processors & International Transfers",
                "content": (
                    "To deliver the service we engage the following sub-processors. Each is bound by "
                    "its own data processing agreement with contractual confidentiality obligations. "
                    "Where processing occurs outside India, we rely on the transfer mechanisms permitted "
                    "under DPDPA § 16 and ensure that the receiving jurisdiction is not a country the "
                    "Central Government has restricted.\n\n"
                    "**AI / LLM Processors**\n"
                    "- **Google LLC / Google Cloud India (Gemini 2.5 Pro, Gemini 2.0 Flash)** — extraction, "
                    "evaluation, drafting, reranking, routing. Region: Google Cloud `asia-south1` (Mumbai) "
                    "where available; otherwise global endpoints. Google's enterprise API terms state "
                    "that customer prompts are **not used** to train Google's foundation models.\n"
                    "- **OpenAI LLC, USA (text-embedding-3-small)** — generation of vector embeddings for "
                    "retrieval. Document text is transmitted to the OpenAI API. OpenAI's enterprise API "
                    "terms state that API inputs are **not used** to train OpenAI's foundation models and "
                    "are retained for a maximum of 30 days for abuse monitoring, after which they are deleted.\n\n"
                    "**Infrastructure**\n"
                    "- **Google Cloud Platform (Cloud Run, Cloud SQL PostgreSQL, Cloud Storage, Secret Manager)** — "
                    "application hosting, database, file storage, and secret management. Primary region: `asia-south1`.\n\n"
                    "**Payments**\n"
                    "- **Razorpay Software Pvt. Ltd., Bengaluru, India** — payment processing. PCI-DSS "
                    "Level 1 compliant. Razorpay is the Data Fiduciary for card/bank data it handles.\n\n"
                    "**Communications**\n"
                    "- **Twilio SendGrid (via SMTP)** — transactional email delivery for reports, notices, "
                    "and account notifications.\n\n"
                    "**International transfer disclosure:** OpenAI processing occurs in the United States; "
                    "Google Gemini may fail over to regions outside India subject to Google's routing. "
                    "By accepting this Policy you provide informed consent under DPDPA § 16 for such "
                    "cross-border transfers. You may withdraw consent at any time by deleting your data "
                    "(Section 7(c)); however, this will terminate your access to AI-powered features."
                ),
            },
            {
                "heading": "6. Retention Periods",
                "content": (
                    "We retain personal data only as long as necessary for the purposes identified above "
                    "and in accordance with applicable Indian law.\n\n"
                    "| Data Category | Retention Period |\n"
                    "|---|---|\n"
                    "| Uploaded documents & ChromaDB vector embeddings | Until you delete them or invoke Right to Erasure |\n"
                    "| Analysis results (audits, recon, bank analysis, etc.) | Until you delete them or invoke Right to Erasure |\n"
                    "| Chat history | Until you delete your data |\n"
                    "| Account profile | Until account deletion |\n"
                    "| Billing records (Credit Transactions, invoices) | **8 years** post-transaction (Income-tax Act § 44AA read with Rule 6F and GST Act § 36) — retained even after erasure to meet statutory obligations |\n"
                    "| Audit logs | **Minimum 180 days**, commonly retained up to 7 years as security and compliance records; not deleted on Right to Erasure |\n"
                    "| Subscription records | **8 years** post-cancellation for tax audit purposes |\n"
                    "| Backup snapshots | Rolling 30-day window; deletion from primary storage propagates within 30 days |\n\n"
                    "When you invoke Right to Erasure (Section 7(c)), we delete (a) all uploaded documents "
                    "and their vector embeddings, (b) analysis results, (c) chat history, (d) client records "
                    "and calendar events you created. We **retain** the user account row, subscription "
                    "history, credit transactions, and audit logs because these constitute compliance records "
                    "under the Income-tax Act, GST Act, and DPDPA § 8(8). The retained records are marked with "
                    "a `data_deleted_at` timestamp and cannot be used for any purpose other than statutory "
                    "reporting and audit."
                ),
            },
            {
                "heading": "7. Your Rights as a Data Principal",
                "content": (
                    "Under DPDPA §§ 11–14, you have the following rights, and we have implemented "
                    "self-service endpoints for each:\n\n"
                    "**(a) Right to Access & Portability (DPDPA § 11)** — Obtain a copy of all personal "
                    "data we hold about you in a structured, commonly-used format.\n"
                    "- *How:* Settings → Data Privacy → **Export My Data**, or call `GET /api/v1/account/data-export`.\n"
                    "- *Delivery:* JSON download, usually within seconds.\n\n"
                    "**(b) Right to Correction (DPDPA § 12)** — Correct inaccurate or incomplete data.\n"
                    "- *How:* Settings → Profile, or email the Grievance Officer for fields not editable in-app.\n\n"
                    "**(c) Right to Erasure (DPDPA § 12)** — Have your personal data deleted.\n"
                    "- *How:* Settings → Data Privacy → **Delete My Data**, or call `DELETE /api/v1/account/data`.\n"
                    "- *Scope:* All uploaded documents, vector embeddings, analysis results, chat history, "
                    "clients, calendar entries, blueprints are permanently deleted. See Section 6 for "
                    "data retained for statutory reasons.\n"
                    "- *Confirmation:* A summary of deleted items is returned immediately.\n\n"
                    "**(d) Right to Withdraw Consent (DPDPA § 6(4))** — Withdraw consent previously given.\n"
                    "- *How:* Invoking Right to Erasure also withdraws consent for AI processing. You may "
                    "also withdraw selectively by contacting the Grievance Officer.\n"
                    "- *Consequence:* AI-powered features become unavailable.\n\n"
                    "**(e) Right to Nominate (DPDPA § 13)** — Nominate another person to exercise these "
                    "rights on your behalf in case of death or incapacity.\n"
                    "- *How:* Email the Grievance Officer with the nominee's details. We will record the "
                    "nomination against your account.\n\n"
                    "**(f) Right to Grievance Redressal (DPDPA § 14)** — Raise a grievance at any time.\n"
                    "- *How:* Email the Grievance Officer as set out in Section 2.\n"
                    "- *Response:* Acknowledgement within 72 hours, substantive response within 30 days.\n\n"
                    "We do not charge any fee for exercising these rights."
                ),
            },
            {
                "heading": "8. Security Measures",
                "content": (
                    "We implement reasonable security practices and procedures commensurate with the "
                    "nature and sensitivity of the personal data processed, aligned with the ISO/IEC "
                    "27001:2022 framework as recognised under IT Rules 2011 Rule 8:\n\n"
                    "**Encryption**\n"
                    "- All data in transit is protected by TLS 1.2 or higher (HSTS enabled; HTTP redirected to HTTPS).\n"
                    "- Data at rest in Cloud SQL (PostgreSQL) and Cloud Storage is encrypted with Google-managed keys (AES-256).\n"
                    "- Passwords are hashed with bcrypt (cost factor 12).\n\n"
                    "**Access Control**\n"
                    "- JWT access tokens with 1-week expiry; tokens invalidated on logout and password change.\n"
                    "- Per-user data isolation: each user's documents, vector embeddings, and analysis results "
                    "are scoped by `user_id`; cross-user access is blocked at the query layer and the storage "
                    "layer (`user_sessions/{user_id}/vector_db/`, GCS prefix `{user_id}/`).\n"
                    "- Least-privilege IAM for Cloud Run → Cloud SQL / Cloud Storage service accounts.\n"
                    "- Production secrets are stored in Google Secret Manager, never in environment files or source code.\n\n"
                    "**Application-Level Defences**\n"
                    "- Rate limiting on authentication endpoints (10 requests/minute/IP via slowapi).\n"
                    "- CORS restricted to an allow-list of trusted origins; webhook signature validation on all Razorpay callbacks.\n"
                    "- SQL injection prevention via SQLAlchemy ORM with parameterised queries.\n"
                    "- Dependency scanning and routine security updates.\n\n"
                    "**Monitoring**\n"
                    "- Structured audit logs for every sensitive action (login, upload, delete, export, consent update).\n"
                    "- Cloud Run request logs retained for security investigation.\n\n"
                    "Despite these measures, no system is absolutely secure. If you believe your account "
                    "has been compromised, email the Grievance Officer immediately and change your password."
                ),
            },
            {
                "heading": "9. Children's Data",
                "content": (
                    "The Platform is intended exclusively for use by Chartered Accountants, tax "
                    "professionals, and business owners aged **18 years or older**. We do not knowingly "
                    "collect personal data from children (defined as individuals under 18 under DPDPA § 9). "
                    "If we become aware that we have inadvertently collected data from a child without "
                    "verifiable parental or guardian consent, we will delete that data without undue delay.\n\n"
                    "If you are a parent or guardian and believe that a child has provided personal data "
                    "to the Platform, please contact the Grievance Officer so we can investigate and "
                    "remove the data. We will not process children's personal data for tracking, "
                    "behavioural monitoring, or targeted advertising under any circumstances."
                ),
            },
            {
                "heading": "10. Cookies & Local Storage",
                "content": (
                    "We use a small number of cookies and browser local-storage items, all strictly "
                    "necessary for the Platform to function. We do **not** use advertising cookies, "
                    "third-party analytics trackers, or behavioural profiling cookies.\n\n"
                    "| Name | Purpose | Duration |\n"
                    "|---|---|---|\n"
                    "| `access_token` (localStorage) | Stores the JWT for authenticated API calls | 7 days / until logout |\n"
                    "| `user_profile` (localStorage) | Caches profile for UI rendering | 7 days / until logout |\n"
                    "| `consent_version` (localStorage) | Tracks which Policy version the user accepted | Until manually cleared |\n"
                    "| Session cookie (HTTP-only) | Only used by Razorpay during payment redirect | Session |\n\n"
                    "You may clear cookies and local storage from your browser settings at any time; "
                    "doing so will log you out but will not delete server-side data."
                ),
            },
            {
                "heading": "11. Breach Notification",
                "content": (
                    "In the event of a personal data breach that is likely to result in risk to the "
                    "rights of affected Data Principals, we commit to:\n\n"
                    "- Notifying the **Data Protection Board of India** in the form and manner prescribed "
                    "under DPDPA § 8(6), as soon as reasonably practicable and no later than the statutory "
                    "deadline set by the Board;\n"
                    "- Notifying **affected Data Principals** by email (to the registered address) and an "
                    "in-app banner with a description of the breach, the categories of data affected, the "
                    "likely consequences, and the mitigation steps being taken;\n"
                    "- Cooperating fully with any Board investigation and preserving evidence as required.\n\n"
                    "We maintain an incident response runbook covering detection, containment, "
                    "eradication, recovery, and post-incident review."
                ),
            },
            {
                "heading": "12. Policy Updates & Re-Consent",
                "content": (
                    "We may update this Policy from time to time to reflect changes in our practices, "
                    "the law, or the services we offer. When we make material changes we will:\n\n"
                    "1. Bump the `CURRENT_CONSENT_VERSION` and the `effective_date` at the top of this document.\n"
                    "2. Display a persistent consent banner on the dashboard asking you to review and "
                    "re-accept the updated Policy before continuing to use AI-powered features.\n"
                    "3. Log the acceptance event in the audit trail with the new version.\n\n"
                    "The current version is **" + CURRENT_CONSENT_VERSION + "**, effective " + EFFECTIVE_DATE + ". "
                    "If you have previously accepted an earlier version, you will be asked to re-accept on "
                    "your next login. Non-material changes (typography, clarifications, non-operational "
                    "updates) may be made without a version bump but will still be dated in this document."
                ),
            },
            {
                "heading": "13. Contact",
                "content": (
                    f"For any privacy-related query, grievance, or request to exercise your rights, "
                    f"please contact:\n\n"
                    f"- **Grievance Officer:** {grievance_name}\n"
                    f"- **Email:** {grievance_email}\n"
                    f"- **Postal address:** As published on our website contact page\n"
                    f"- **Response time:** Acknowledgement within 72 hours; substantive response within 30 days\n\n"
                    "You may also exercise most rights directly from Settings → Data Privacy without "
                    "needing to contact us. This Policy is published in English; if a translation is "
                    "provided in any other language, the English version shall prevail in the event of "
                    "any conflict."
                ),
            },
        ],
    }


def get_terms_of_service() -> dict:
    """Returns structured Terms of Service content.

    Shape matches privacy policy (sections with heading + markdown content).
    """
    grievance_name, grievance_email = _grievance_officer()

    return {
        "version": CURRENT_CONSENT_VERSION,
        "effective_date": EFFECTIVE_DATE,
        "last_updated": EFFECTIVE_DATE,
        "title": "Terms of Service — Legal AI Expert",
        "sections": [
            {
                "heading": "1. Acceptance & Eligibility",
                "content": (
                    "These Terms of Service (\"**Terms**\") form a legally binding agreement between you "
                    "(\"**you**\", \"**User**\") and the operator of Legal AI Expert (\"**we**\", "
                    "\"**us**\", \"**the Platform**\"). By creating an account, clicking \"I Agree\" "
                    "during registration, or accessing any part of the Platform, you confirm that:\n\n"
                    "- You are at least **18 years old** and have legal capacity to enter into a binding contract under Indian law;\n"
                    "- You are a practising Chartered Accountant, tax professional, business owner, or an authorised representative thereof;\n"
                    "- The information you provide at registration is accurate and complete;\n"
                    "- Where you upload documents belonging to your clients, you have obtained all necessary client authorisations and are acting as a lawful Data Fiduciary under DPDPA;\n"
                    "- You accept these Terms and the accompanying Privacy Policy in full.\n\n"
                    "If you do not agree to any part of these Terms, you must not use the Platform. We "
                    "reserve the right to refuse service, suspend, or terminate accounts that we reasonably "
                    "believe are being used in contravention of these Terms."
                ),
            },
            {
                "heading": "2. Service Description",
                "content": (
                    "Legal AI Expert is an **AI-assisted compliance workbench** that offers the following "
                    "capabilities (subject to your subscription plan and credit balance):\n\n"
                    "- Document ingestion and extraction (PDF parsing + OCR)\n"
                    "- Multi-agent compliance audits with ground-truth grounded evaluation\n"
                    "- GST Reconciliation (GSTR-1 / GSTR-3B / GSTR-2A)\n"
                    "- GSTR-9 Annual Reconciliation\n"
                    "- Bank Statement Analyzer with statutory flag detection\n"
                    "- Capital Gains computation (equity, debt, property)\n"
                    "- Depreciation schedule (Income-tax Act and Companies Act)\n"
                    "- Advance Tax computation\n"
                    "- Income Tax and GST Notice Reply drafting\n"
                    "- Client and calendar management\n"
                    "- Chat-based research assistance across Indian tax regulations\n"
                    "- Standalone PDF Redaction Tool (free desktop utility)\n\n"
                    "**The Platform is a decision-support tool, not a substitute for professional judgment.** "
                    "All outputs are AI-generated and must be reviewed, corrected where necessary, and "
                    "approved by a qualified Chartered Accountant before being filed with any tax authority "
                    "or relied upon for any statutory purpose."
                ),
            },
            {
                "heading": "3. Account Responsibilities",
                "content": (
                    "You are responsible for:\n\n"
                    "- Maintaining the confidentiality of your login credentials and JWT tokens;\n"
                    "- All activities that occur under your account, whether authorised or not;\n"
                    "- Promptly notifying us at the Grievance Officer address if you suspect any unauthorised use or breach;\n"
                    "- Keeping your email address and contact details up to date;\n"
                    "- Ensuring that documents you upload do not contain malicious payloads (macros, embedded scripts, malware);\n"
                    "- Ensuring that you have the lawful authority to upload client documents and that doing so does not violate any client engagement letter, NDA, or professional standard.\n\n"
                    "We are not liable for any loss arising from your failure to comply with these "
                    "responsibilities. You must not create more than one account per natural person "
                    "unless explicitly authorised by us for team or enterprise billing."
                ),
            },
            {
                "heading": "4. Subscriptions, Credits & Refunds",
                "content": (
                    "**Plans and credits.** The Platform operates on a credit-based consumption model "
                    "layered over plan tiers:\n\n"
                    "| Plan | Price (INR) | Credits |\n"
                    "|---|---|---|\n"
                    "| Free Trial | ₹0 | 75 |\n"
                    "| Starter | ₹499 / month | 100 |\n"
                    "| Professional | ₹999 / month | 300 |\n"
                    "| Enterprise | ₹2,499 / month | 1,000 |\n\n"
                    "Different features consume different credit amounts. The current costs are published "
                    "in the in-app pricing page and may be updated with 15 days' notice.\n\n"
                    "**Payments.** All payments are processed by Razorpay. By subscribing you authorise "
                    "Razorpay to charge your chosen payment instrument and agree to Razorpay's own terms "
                    "of service.\n\n"
                    "**Refund policy.** Credits are **non-refundable and non-transferable**. Subscription "
                    "fees are refundable only in the following limited circumstances:\n"
                    "- Duplicate / accidental charge — full refund within 7 days of the charge;\n"
                    "- Platform-wide outage exceeding 24 continuous hours during a billing cycle — pro-rata refund;\n"
                    "- Billing error attributable to us — corrected charge or refund as appropriate.\n\n"
                    "Refund requests must be raised with the Grievance Officer within 30 days of the "
                    "triggering event. Refunds are processed back to the original payment instrument "
                    "within 7–10 business days of approval."
                ),
            },
            {
                "heading": "5. Acceptable Use",
                "content": (
                    "You agree **not** to use the Platform to:\n\n"
                    "- Upload personal data of any third party without having obtained their consent or the lawful authority to do so;\n"
                    "- Submit content that is illegal, defamatory, obscene, or infringes any intellectual property right;\n"
                    "- Engage in tax evasion, money-laundering, or any other financial crime;\n"
                    "- Circumvent or attempt to circumvent plan tiers, credit limits, rate limits, or access controls;\n"
                    "- Reverse-engineer, decompile, or extract the source code, AI model weights, or proprietary prompts of the Platform;\n"
                    "- Upload files containing viruses, ransomware, worms, or other malicious code;\n"
                    "- Use automated scrapers, bots, or headless browsers against the API except through documented endpoints with valid authentication;\n"
                    "- Resell, sublicense, or white-label the Platform or its outputs without our prior written consent;\n"
                    "- Impersonate any person or entity, or misrepresent your affiliation with any organisation.\n\n"
                    "Violation of any Acceptable Use rule is grounds for immediate suspension, termination "
                    "without refund, and reporting to competent authorities where legally required."
                ),
            },
            {
                "heading": "6. Intellectual Property",
                "content": (
                    "**Platform IP.** All software, design, database schema, AI prompts, reports templates, "
                    "blueprints, documentation, trademarks, logos, and other materials of the Platform are "
                    "owned by us or our licensors and protected by Indian and international copyright, "
                    "trademark, and trade-secret laws. Nothing in these Terms transfers any ownership or "
                    "grants any licence except the limited non-exclusive right to access and use the "
                    "Platform in accordance with these Terms during the subscription period.\n\n"
                    "**Your content.** You retain all rights, title, and interest in the documents you "
                    "upload. You grant us a limited, worldwide, royalty-free licence to store, process, "
                    "and transmit your content **solely** for the purpose of delivering the service to "
                    "you. This licence terminates when you delete the content or your account, subject "
                    "to Section 6 of the Privacy Policy (statutory retention).\n\n"
                    "**AI-generated outputs.** You may freely use AI-generated reports, reconciliation "
                    "results, and draft notices produced from your inputs for any lawful purpose, including "
                    "filing with tax authorities and sharing with your clients. We do not claim ownership "
                    "of the outputs. However, the underlying Platform, prompts, and templates that produced "
                    "those outputs remain our intellectual property."
                ),
            },
            {
                "heading": "7. Disclaimer — AI-Assisted Outputs",
                "content": (
                    "**The Platform is a decision-support tool. It is not legal, tax, financial, or "
                    "professional advice.**\n\n"
                    "All analysis, reports, reconciliation results, notice replies, compliance flags, "
                    "and recommendations produced by the Platform are generated by large language models "
                    "(Google Gemini 2.5 Pro / 2.0 Flash; OpenAI embeddings for retrieval). These models:\n\n"
                    "- May occasionally produce factually incorrect statements (\"hallucinations\");\n"
                    "- May misinterpret ambiguous scanned text or non-standard document layouts;\n"
                    "- Do not have real-time knowledge of the most recent amendments to the Income-tax Act, GST Act, or related rules and circulars;\n"
                    "- Cannot account for client-specific facts that are not visible in the uploaded documents.\n\n"
                    "**You must independently verify every figure, citation, and recommendation with the "
                    "actual primary sources** (bare Act, rules, circulars, case law, departmental portals) "
                    "and apply your professional judgement as a qualified Chartered Accountant before filing "
                    "any return, replying to any notice, or advising any client. We strongly advise running "
                    "all outputs through your firm's standard review and approval workflow.\n\n"
                    "Without limiting the generality of the foregoing, we provide the Platform **\"AS IS\" "
                    "and \"AS AVAILABLE\"** and expressly disclaim all warranties of any kind, whether "
                    "express, implied, or statutory, including warranties of merchantability, fitness for "
                    "a particular purpose, accuracy, completeness, reliability, and non-infringement."
                ),
            },
            {
                "heading": "8. Limitation of Liability",
                "content": (
                    "To the maximum extent permitted by applicable law:\n\n"
                    "- We shall not be liable for any indirect, incidental, special, consequential, "
                    "exemplary, or punitive damages, including but not limited to loss of profits, loss "
                    "of data, loss of goodwill, business interruption, regulatory penalties, interest on "
                    "tax demands, or cost of substitute services, arising out of or in connection with "
                    "your use of, or inability to use, the Platform — even if we have been advised of "
                    "the possibility of such damages.\n"
                    "- Our total aggregate liability for any and all claims arising out of or in "
                    "connection with the Platform or these Terms shall not exceed the **total amount "
                    "of subscription fees actually paid by you to us during the twelve (12) months "
                    "immediately preceding the event giving rise to the claim**.\n"
                    "- Some jurisdictions do not allow the exclusion or limitation of certain damages; "
                    "in such jurisdictions, the limitations above shall apply to the fullest extent "
                    "permitted by law.\n\n"
                    "Nothing in these Terms excludes or limits our liability for death or personal "
                    "injury caused by our negligence, fraud, or any liability that cannot be excluded "
                    "under Indian law."
                ),
            },
            {
                "heading": "9. Indemnity",
                "content": (
                    "You agree to indemnify, defend, and hold harmless the operators of Legal AI Expert, "
                    "their directors, employees, affiliates, and service providers from and against any "
                    "and all claims, demands, actions, losses, liabilities, damages, costs, and expenses "
                    "(including reasonable legal fees) arising out of or relating to:\n\n"
                    "- Your breach of these Terms or the Privacy Policy;\n"
                    "- Your violation of any applicable law, regulation, or third-party right;\n"
                    "- Your upload of content for which you did not have the lawful authority;\n"
                    "- Reliance on AI-generated output without independent verification by a qualified professional.\n\n"
                    "We will provide reasonable cooperation in defending any such claim at your expense "
                    "and may participate in the defence with counsel of our own choosing."
                ),
            },
            {
                "heading": "10. Suspension, Termination & Post-Termination",
                "content": (
                    "**By you.** You may terminate your account at any time from Settings → Data Privacy "
                    "by invoking Right to Erasure. Your subscription will not auto-renew after the current "
                    "billing cycle.\n\n"
                    "**By us.** We may suspend or terminate your access immediately, without notice and "
                    "without refund, if you:\n"
                    "- Breach these Terms (including Acceptable Use);\n"
                    "- Fail to pay any subscription fee when due;\n"
                    "- Engage in activity that poses a security risk to the Platform or other users;\n"
                    "- Use the Platform for an unlawful purpose.\n\n"
                    "**Post-termination.** Upon termination we will (a) delete your documents, embeddings, "
                    "analysis results, and chat history from primary storage within 30 days; (b) retain "
                    "subscription records, credit transactions, and audit logs for the statutory periods "
                    "identified in Section 6 of the Privacy Policy; (c) continue to be bound by the "
                    "confidentiality obligations for any information we still hold."
                ),
            },
            {
                "heading": "11. Governing Law & Dispute Resolution",
                "content": (
                    "These Terms are governed by and construed in accordance with the **laws of India**, "
                    "without reference to its conflict-of-laws principles.\n\n"
                    "**Escalation sequence:**\n\n"
                    "1. **Good-faith negotiation.** The parties shall first attempt to resolve any dispute "
                    "through good-faith discussion by contacting the Grievance Officer. Most disputes can "
                    "be resolved at this stage.\n"
                    "2. **Mediation.** If the matter cannot be resolved within 30 days of notice, the "
                    "parties shall attempt mediation at a mutually agreeable venue in Bengaluru.\n"
                    "3. **Courts.** Any dispute that cannot be resolved by mediation shall be subject to "
                    "the **exclusive jurisdiction of the courts in Bengaluru, Karnataka, India**. Nothing "
                    "prevents either party from seeking urgent injunctive relief in any competent court "
                    "where it is required to protect rights pending final resolution.\n\n"
                    "Alternatively, where both parties agree in writing, a dispute may be referred to "
                    "binding arbitration under the Arbitration and Conciliation Act, 1996, by a sole "
                    "arbitrator in Bengaluru, in the English language, in accordance with the rules of "
                    "a recognised Indian arbitral institution."
                ),
            },
            {
                "heading": "12. Force Majeure",
                "content": (
                    "We shall not be liable for any failure or delay in performance caused by events "
                    "beyond our reasonable control, including but not limited to: acts of God, natural "
                    "disasters, war, civil unrest, terrorist acts, government actions, labour disputes, "
                    "epidemics or pandemics, failures or disruptions of internet service providers, "
                    "cloud infrastructure outages (Google Cloud Platform), failures of upstream AI "
                    "processors (Google Gemini, OpenAI), or widespread power failures. During a force "
                    "majeure event we will use reasonable efforts to mitigate the impact and restore "
                    "service as soon as practicable."
                ),
            },
            {
                "heading": "13. Miscellaneous",
                "content": (
                    "**Entire agreement.** These Terms, together with the Privacy Policy and any "
                    "plan-specific terms presented at checkout, constitute the entire agreement between "
                    "you and us with respect to the Platform and supersede any prior or contemporaneous "
                    "communications.\n\n"
                    "**Severability.** If any provision of these Terms is held to be invalid or "
                    "unenforceable, the remaining provisions shall continue in full force and effect.\n\n"
                    "**No waiver.** Our failure to enforce any right or provision shall not constitute "
                    "a waiver of that right or provision.\n\n"
                    "**Assignment.** You may not assign or transfer these Terms without our prior "
                    "written consent. We may assign these Terms to any successor in interest in "
                    "connection with a merger, acquisition, or sale of substantially all of our assets.\n\n"
                    "**Notices.** Legal notices to us must be sent to the Grievance Officer email. "
                    "Notices to you may be sent to your registered email address or displayed in-app.\n\n"
                    "**Changes to these Terms.** We may amend these Terms from time to time. Material "
                    "amendments will be communicated by email and by in-app banner and will be subject "
                    "to re-acceptance via the consent mechanism. Continued use of the Platform after "
                    "an amendment constitutes acceptance of the amended Terms.\n\n"
                    f"**Contact:** {grievance_name} — {grievance_email}."
                ),
            },
        ],
    }


def get_ai_processing_disclosure() -> dict:
    """Returns the AI processing disclosure text shown on upload pages."""
    return {
        "version": CURRENT_CONSENT_VERSION,
        "short": (
            "Your documents are processed using Google Gemini AI and OpenAI for analysis. "
            "Use our free PDF Redaction Tool to remove sensitive information before uploading."
        ),
        "detailed": (
            "By uploading documents, you acknowledge that:\n"
            "1. Document text is sent to Google Gemini 2.5 Pro / 2.0 Flash for extraction, evaluation, and drafting.\n"
            "2. Document text is sent to OpenAI (text-embedding-3-small) for vector embedding used in retrieval.\n"
            "3. Under enterprise API agreements, neither Google nor OpenAI uses your data to train their foundation models.\n"
            "4. OpenAI may retain API inputs for up to 30 days for abuse monitoring, after which they are deleted.\n"
            "5. Google Gemini processing may occur in regions outside India subject to Google's routing.\n"
            "6. We do not sell your data or use it for advertising.\n"
            "7. You can invoke Right to Erasure at any time from Settings → Data Privacy.\n"
            "8. We strongly recommend redacting PAN, Aadhaar, names, and bank account numbers before uploading."
        ),
        "redaction_tool_message": (
            "Protect your clients' sensitive data — download our free PDF Redaction Tool "
            "to permanently remove PAN, Aadhaar, bank account numbers, and personal names "
            "from documents before uploading. The tool uses the same underlying technology "
            "(PyMuPDF apply_redactions) used by law firms and government agencies for "
            "permanent document redaction — the text is removed from the PDF's content "
            "stream, not merely covered by a black box."
        ),
        "processors": [
            {
                "name": "Google Gemini",
                "operator": "Google LLC / Google Cloud India",
                "purpose": "Extraction, evaluation, drafting, reranking, routing",
                "region": "asia-south1 (Mumbai) where available; global failover possible",
                "training_use": "Not used for model training under enterprise API terms",
            },
            {
                "name": "OpenAI Embeddings",
                "operator": "OpenAI LLC, United States",
                "purpose": "Vector embeddings for retrieval",
                "region": "United States",
                "training_use": "Not used for model training; retained up to 30 days for abuse monitoring",
            },
            {
                "name": "Google Cloud Platform",
                "operator": "Google Cloud India Pvt. Ltd.",
                "purpose": "Hosting, database, storage, secret management",
                "region": "asia-south1 (Mumbai)",
                "training_use": "Not applicable (infrastructure)",
            },
            {
                "name": "Razorpay",
                "operator": "Razorpay Software Pvt. Ltd., Bengaluru",
                "purpose": "Payment processing",
                "region": "India",
                "training_use": "Not applicable",
            },
            {
                "name": "Twilio SendGrid",
                "operator": "Twilio Inc. (via SMTP relay)",
                "purpose": "Transactional email delivery",
                "region": "Global",
                "training_use": "Not applicable",
            },
        ],
    }
