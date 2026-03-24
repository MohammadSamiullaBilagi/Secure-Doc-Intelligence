import logging
from datetime import datetime
from io import BytesIO

logger = logging.getLogger(__name__)


def _safe_get(obj, attr: str, default=""):
    """Safely get an attribute from a Pydantic object or a dict."""
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)


def _sanitize_text(text: str) -> str:
    """Replace Unicode characters that Helvetica can't render with ASCII equivalents."""
    if not text:
        return ""
    replacements = {
        '\u2018': "'", '\u2019': "'",
        '\u201c': '"', '\u201d': '"',
        '\u2013': '-', '\u2014': '--',
        '\u2026': '...',
        '\u2022': '*',
        '\u00a0': ' ',
        '\u2032': "'", '\u2033': '"',
        '\u00b7': '.',
        '\u2010': '-', '\u2011': '-',
        '\u20b9': 'Rs.',
        '\u00e9': 'e', '\u00e8': 'e',
        '\u201a': ',',
        '\u00ad': '-',
        '\u200b': '',
        '\u200c': '', '\u200d': '',
        '\ufeff': '',
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text.encode('latin-1', errors='replace').decode('latin-1')


def _break_long_words(text: str, max_word_len: int = 60) -> str:
    """Break any single 'word' longer than max_word_len chars."""
    if not text:
        return ""
    lines = text.split('\n')
    result_lines = []
    for line in lines:
        words = line.split(' ')
        new_words = []
        for word in words:
            while len(word) > max_word_len:
                new_words.append(word[:max_word_len])
                word = word[max_word_len:]
            new_words.append(word)
        result_lines.append(' '.join(new_words))
    return '\n'.join(result_lines)


def _safe_multi_cell(pdf, w, h: int, text: str):
    """Write text via multi_cell, with x-position reset and overflow protection."""
    pdf.set_x(pdf.l_margin)
    try:
        pdf.multi_cell(0, h, text)
    except Exception:
        pdf.set_x(pdf.l_margin)
        try:
            pdf.multi_cell(0, h, text[:2000] + "... [truncated]")
        except Exception:
            pdf.cell(0, h, "[content could not be rendered]", ln=True)


class ReportService:
    """PDF audit report generation service."""

    @staticmethod
    def compute_compliance_score(audit_state: dict) -> tuple:
        """Compute compliance score and open violations from audit state.

        Returns:
            (score, open_violations) where score is 0-100 float and
            open_violations is count of NON_COMPLIANT checks.
        """
        audit_results = audit_state.get("audit_results", []) if isinstance(audit_state, dict) else []
        if not audit_results:
            return (None, 0)

        total = len(audit_results)
        passed = 0
        violations = 0
        for r in audit_results:
            status = str(_safe_get(r, 'compliance_status', '')).upper()
            if status in ('COMPLIANT', 'TRUE'):
                passed += 1
            elif status in ('NON_COMPLIANT', 'FALSE'):
                violations += 1

        score = round((passed / total) * 100, 1) if total > 0 else 0.0
        return (score, violations)

    @staticmethod
    def _render_ca_header(pdf, ca_info: dict):
        """Render the CA branding header block on a PDF page."""
        if not ca_info:
            return

        firm = ca_info.get("firm_name")
        ca_name = ca_info.get("ca_name")
        icai = ca_info.get("icai_membership_number")
        address = ca_info.get("firm_address")
        phone = ca_info.get("firm_phone")
        email = ca_info.get("firm_email")

        if firm:
            pdf.set_font("Helvetica", "B", 14)
            pdf.cell(0, 8, _sanitize_text(firm), ln=True, align="C")
        if ca_name or icai:
            pdf.set_font("Helvetica", "I", 10)
            parts = []
            if ca_name:
                parts.append(ca_name)
            if icai:
                parts.append(f"ICAI M. No. {icai}")
            pdf.cell(0, 6, _sanitize_text(" | ".join(parts)), ln=True, align="C")

        # Contact info line
        contact_parts = []
        if address:
            contact_parts.append(address)
        if phone:
            contact_parts.append(f"Ph: {phone}")
        if email:
            contact_parts.append(email)
        if contact_parts:
            pdf.set_font("Helvetica", "", 9)
            pdf.cell(0, 5, _sanitize_text(" | ".join(contact_parts)), ln=True, align="C")

        # Separator line
        pdf.set_draw_color(0, 0, 0)
        y = pdf.get_y() + 2
        pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
        pdf.ln(6)

    @staticmethod
    def generate_compliance_pdf(
        document_name: str,
        risk_report: str,
        audit_state: dict,
        client_info: dict = None,
        ca_info: dict = None,
    ) -> BytesIO:
        """Generate a professional client-ready PDF audit report using fpdf2.

        Args:
            document_name: Name of the audited document.
            risk_report: Executive risk assessment text.
            audit_state: Full audit state dict with audit_results, remediation_draft, etc.
            client_info: Optional dict with keys: name, gstin.
            ca_info: Optional dict with keys: firm_name, ca_name, icai_membership_number,
                     firm_address, firm_phone, firm_email.
        """
        from fpdf import FPDF

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.set_left_margin(15)
        pdf.set_right_margin(15)
        pdf.add_page()

        effective_w = pdf.w - pdf.l_margin - pdf.r_margin

        # --- CA Branding Header ---
        ReportService._render_ca_header(pdf, ca_info)

        # --- Title ---
        pdf.set_font("Helvetica", "B", 20)
        pdf.cell(0, 15, "COMPLIANCE PRE-CHECK REPORT (INDICATIVE)", ln=True, align="C")
        pdf.ln(3)

        # --- Disclaimer Banner ---
        disclaimer_lines = [
            "AI-ASSISTED INDICATIVE ANALYSIS -- FOR CA REVIEW ONLY",
            "This report identifies potential compliance areas using AI pattern recognition.",
            "All findings must be independently verified by a qualified Chartered Accountant",
            "before advising clients or filing responses. This report does not constitute a",
            "legal opinion, tax advice, or a signed audit report under the Income Tax Act",
            "or GST law.",
        ]
        pdf.set_fill_color(255, 243, 205)   # #FFF3CD amber background
        pdf.set_draw_color(133, 100, 4)     # #856404 amber border
        pdf.set_line_width(0.5)
        banner_x = pdf.l_margin
        banner_y = pdf.get_y()
        line_h = 5
        padding = 4
        banner_h = padding * 2 + line_h * len(disclaimer_lines)
        pdf.rect(banner_x, banner_y, effective_w, banner_h, style="FD")
        pdf.set_xy(banner_x + padding, banner_y + padding)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(133, 100, 4)
        pdf.cell(effective_w - padding * 2, line_h, disclaimer_lines[0], ln=True)
        pdf.set_x(banner_x + padding)
        pdf.set_font("Helvetica", "", 10)
        for line in disclaimer_lines[1:]:
            pdf.cell(effective_w - padding * 2, line_h, line, ln=True)
            pdf.set_x(banner_x + padding)
        pdf.set_text_color(0, 0, 0)
        pdf.set_draw_color(0, 0, 0)
        pdf.set_line_width(0.2)
        pdf.ln(4)

        # --- Client Info ---
        if client_info:
            pdf.set_font("Helvetica", "B", 11)
            client_name = client_info.get("name")
            gstin = client_info.get("gstin")
            if client_name:
                pdf.cell(0, 7, _sanitize_text(f"Prepared For: {client_name}"), ln=True)
            if gstin:
                pdf.cell(0, 7, _sanitize_text(f"GSTIN: {gstin}"), ln=True)
            pdf.ln(3)

        # --- Document name ---
        pdf.set_font("Helvetica", "B", 12)
        safe_doc_name = _break_long_words(_sanitize_text(f"Document: {document_name}"))
        pdf.cell(0, 8, safe_doc_name, ln=True)
        pdf.ln(3)

        # --- Compliance Score ---
        audit_results = audit_state.get("audit_results", []) if isinstance(audit_state, dict) else []
        if audit_results:
            total = len(audit_results)
            passed = sum(
                1 for r in audit_results
                if str(_safe_get(r, 'compliance_status', '')).upper() in ('COMPLIANT', 'TRUE')
            )
            pct = round((passed / total) * 100) if total > 0 else 0

            pdf.set_font("Helvetica", "B", 12)
            score_text = f"Compliance Score: {passed} out of {total} checks passed - {pct}% compliant"
            if pct >= 80:
                pdf.set_text_color(0, 128, 0)
            elif pct >= 50:
                pdf.set_text_color(200, 100, 0)
            else:
                pdf.set_text_color(200, 0, 0)
            pdf.cell(0, 8, _sanitize_text(score_text), ln=True)
            pdf.set_text_color(0, 0, 0)
            pdf.ln(5)

        # --- Executive Summary ---
        try:
            pdf.set_font("Helvetica", "B", 14)
            pdf.cell(0, 10, "Executive Summary", ln=True)
            pdf.set_font("Helvetica", "", 10)
            safe_risk = _break_long_words(_sanitize_text(risk_report or "No risk assessment available."))
            _safe_multi_cell(pdf, effective_w, 6, safe_risk)
            pdf.ln(5)
        except Exception as e:
            logger.error(f"PDF risk report section failed: {e}")

        # --- Findings Summary Table ---
        try:
            if audit_results:
                pdf.set_font("Helvetica", "B", 14)
                pdf.cell(0, 10, "Findings Summary", ln=True)
                pdf.ln(2)

                # Table header
                pdf.set_font("Helvetica", "B", 8)
                pdf.set_fill_color(240, 240, 240)
                col_w = [55, 30, 95]  # Check ID, Status, Key Finding
                pdf.cell(col_w[0], 6, "Check", border=1, fill=True)
                pdf.cell(col_w[1], 6, "Status", border=1, fill=True)
                pdf.cell(col_w[2], 6, "Key Finding", border=1, fill=True)
                pdf.ln()

                # Table rows
                pdf.set_font("Helvetica", "", 7)
                for result in audit_results:
                    status = str(_safe_get(result, 'compliance_status', 'UNKNOWN'))
                    check_id = str(_safe_get(result, 'check_id', ''))
                    violation = str(_safe_get(result, 'violation_details', ''))

                    if status in ("COMPLIANT",):
                        pdf.set_text_color(0, 128, 0)
                        finding = "Compliant"
                    elif status == "INCONCLUSIVE":
                        pdf.set_text_color(100, 100, 180)
                        finding = "Data not found in document"
                    else:
                        pdf.set_text_color(200, 0, 0)
                        finding = violation[:60] + "..." if len(violation) > 60 else violation
                        if finding in ("None", ""):
                            finding = status

                    pdf.cell(col_w[0], 5, _sanitize_text(check_id[:30]), border=1)
                    pdf.cell(col_w[1], 5, _sanitize_text(status), border=1)
                    pdf.cell(col_w[2], 5, _sanitize_text(finding), border=1)
                    pdf.set_text_color(0, 0, 0)
                    pdf.ln()

                pdf.ln(5)

                pdf.set_font("Helvetica", "B", 14)
                pdf.cell(0, 10, "Detailed Findings", ln=True)
                pdf.ln(3)

                for i, result in enumerate(audit_results, 1):
                    try:
                        compliance_status = str(_safe_get(result, 'compliance_status', 'UNKNOWN'))
                        check_id = str(_safe_get(result, 'check_id', f'Check {i}'))
                        focus = str(_safe_get(result, 'focus', ''))
                        violation = str(_safe_get(result, 'violation_details', ''))
                        evidence = str(_safe_get(result, 'evidence', ''))
                        amendment = str(_safe_get(result, 'suggested_amendment', ''))
                        financial_impact = _safe_get(result, 'financial_impact', None)
                        confidence = str(_safe_get(result, 'confidence', ''))

                        if compliance_status in ('True', 'true', True):
                            compliance_status = 'COMPLIANT'
                        elif compliance_status in ('False', 'false', False):
                            compliance_status = 'NON_COMPLIANT'

                        if compliance_status == "COMPLIANT":
                            status_color = (0, 128, 0)
                        elif compliance_status == "PARTIAL":
                            status_color = (200, 100, 0)
                        elif compliance_status == "INCONCLUSIVE":
                            status_color = (100, 100, 180)
                        else:
                            status_color = (200, 0, 0)

                        # --- Check header with status ---
                        pdf.set_font("Helvetica", "B", 10)
                        pdf.set_text_color(*status_color)
                        header = f"{check_id}: {compliance_status}"
                        if confidence and confidence != "LOW":
                            header += f"  [{confidence}]"
                        pdf.cell(0, 7, _break_long_words(_sanitize_text(header)), ln=True)
                        pdf.set_text_color(0, 0, 0)

                        pdf.set_font("Helvetica", "", 8)

                        # Focus — always show (short)
                        _safe_multi_cell(pdf, effective_w, 4, _break_long_words(_sanitize_text(f"Focus: {focus}")))

                        # Evidence — truncated to 200 chars for readability
                        if evidence and evidence.strip() not in ("None", ""):
                            trunc_evidence = evidence[:200] + ("..." if len(evidence) > 200 else "")
                            _safe_multi_cell(pdf, effective_w, 4, _break_long_words(_sanitize_text(f"Evidence: {trunc_evidence}")))

                        # For non-compliant: show violation, action, and financial impact
                        if compliance_status not in ("COMPLIANT", "INCONCLUSIVE"):
                            if violation and violation.strip() not in ("None", ""):
                                trunc_violation = violation[:250] + ("..." if len(violation) > 250 else "")
                                pdf.set_font("Helvetica", "B", 8)
                                pdf.set_text_color(180, 0, 0)
                                _safe_multi_cell(pdf, effective_w, 4, _break_long_words(_sanitize_text(f"* Issue: {trunc_violation}")))
                                pdf.set_text_color(0, 0, 0)

                            if amendment and amendment.strip() not in ("None", ""):
                                trunc_amend = amendment[:250] + ("..." if len(amendment) > 250 else "")
                                pdf.set_font("Helvetica", "", 8)
                                _safe_multi_cell(pdf, effective_w, 4, _break_long_words(_sanitize_text(f"-> Action: {trunc_amend}")))

                            # Financial impact line
                            if financial_impact and isinstance(financial_impact, dict):
                                amt = financial_impact.get('estimated_amount')
                                calc = financial_impact.get('calculation', '')
                                if amt:
                                    fi_text = f"Financial Impact: Rs. {amt:,.0f}"
                                    if calc:
                                        fi_text += f" ({calc[:80]})"
                                    pdf.set_font("Helvetica", "B", 8)
                                    pdf.set_text_color(200, 0, 0)
                                    _safe_multi_cell(pdf, effective_w, 4, _break_long_words(_sanitize_text(fi_text)))
                                    pdf.set_text_color(0, 0, 0)

                        pdf.ln(2)
                    except Exception as item_err:
                        logger.error(f"PDF: Failed to render audit result #{i}: {item_err}")
                        pdf.set_font("Helvetica", "", 9)
                        pdf.set_text_color(0, 0, 0)
                        pdf.cell(0, 5, f"[Error rendering check #{i}]", ln=True)
        except Exception as e:
            logger.error(f"PDF audit results section failed: {e}")

        # --- Remediation Required ---
        try:
            remediation = audit_state.get("remediation_draft", {}) if isinstance(audit_state, dict) else {}
            if isinstance(remediation, dict) and remediation.get("requires_action"):
                pdf.set_font("Helvetica", "B", 14)
                pdf.cell(0, 10, "Remediation Required", ln=True)
                pdf.set_font("Helvetica", "", 10)
                _safe_multi_cell(pdf, effective_w, 6, _break_long_words(_sanitize_text(f"Subject: {remediation.get('email_subject', 'N/A')}")))
                _safe_multi_cell(pdf, effective_w, 6, _break_long_words(_sanitize_text(remediation.get("email_body", ""))))
                pdf.ln(5)
        except Exception as e:
            logger.error(f"PDF remediation section failed: {e}")

        # --- Footer ---
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(0, 0, 0)
        footer_parts = ["Generated by Secure Doc-Intelligence", datetime.utcnow().strftime("%Y-%m-%d")]
        if ca_info and ca_info.get("firm_name"):
            footer_parts.append(ca_info["firm_name"])
        pdf.cell(0, 10, _sanitize_text(" | ".join(footer_parts)), ln=True, align="C")

        buffer = BytesIO()
        pdf_bytes = pdf.output()
        buffer.write(pdf_bytes)
        buffer.seek(0)
        return buffer

    @staticmethod
    def generate_notice_reply_pdf(
        notice_type_display: str,
        reply_text: str,
        client_info: dict = None,
        ca_info: dict = None,
    ) -> BytesIO:
        """Generate a formal notice reply PDF."""
        from fpdf import FPDF

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.set_left_margin(15)
        pdf.set_right_margin(15)
        pdf.add_page()

        effective_w = pdf.w - pdf.l_margin - pdf.r_margin

        # CA Branding Header
        ReportService._render_ca_header(pdf, ca_info)

        # Title
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 12, _sanitize_text(f"Reply to {notice_type_display}"), ln=True, align="C")
        pdf.ln(3)

        # Client info
        if client_info:
            pdf.set_font("Helvetica", "B", 11)
            if client_info.get("name"):
                pdf.cell(0, 7, _sanitize_text(f"On behalf of: {client_info['name']}"), ln=True)
            if client_info.get("gstin"):
                pdf.cell(0, 7, _sanitize_text(f"GSTIN: {client_info['gstin']}"), ln=True)
            pdf.ln(3)

        # Reply body
        pdf.set_font("Helvetica", "", 10)
        safe_reply = _break_long_words(_sanitize_text(reply_text or ""))
        for paragraph in safe_reply.split('\n'):
            _safe_multi_cell(pdf, effective_w, 6, paragraph)

        # Footer
        pdf.ln(10)
        pdf.set_font("Helvetica", "I", 8)
        footer_parts = ["Generated by Secure Doc-Intelligence", datetime.utcnow().strftime("%Y-%m-%d")]
        if ca_info and ca_info.get("firm_name"):
            footer_parts.append(ca_info["firm_name"])
        pdf.cell(0, 10, _sanitize_text(" | ".join(footer_parts)), ln=True, align="C")

        buffer = BytesIO()
        pdf_bytes = pdf.output()
        buffer.write(pdf_bytes)
        buffer.seek(0)
        return buffer
