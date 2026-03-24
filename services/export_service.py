import csv
import json
import xml.etree.ElementTree as ET
from io import BytesIO, StringIO


def _safe_get(obj, attr: str, default=""):
    """Safely get an attribute from a Pydantic object or a dict, never returning None."""
    if isinstance(obj, dict):
        val = obj.get(attr, default)
    else:
        val = getattr(obj, attr, default)
    return val if val is not None else default


class ExportService:
    """Export audit results to CSV, Tally XML, or Zoho JSON formats."""

    @staticmethod
    def to_csv(audit_results: list) -> BytesIO:
        """Export audit results as CSV."""
        output = StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Check ID", "Focus", "Compliance Status",
            "Violation Details", "Evidence", "Suggested Remediation"
        ])

        for result in audit_results:
            writer.writerow([
                _safe_get(result, "check_id", ""),
                _safe_get(result, "focus", ""),
                _safe_get(result, "compliance_status", ""),
                _safe_get(result, "violation_details", ""),
                _safe_get(result, "evidence", ""),
                _safe_get(result, "suggested_amendment", ""),
            ])

        buffer = BytesIO(output.getvalue().encode("utf-8"))
        buffer.seek(0)
        return buffer

    @staticmethod
    def to_tally_xml(audit_results: list) -> BytesIO:
        """Export audit results as TallyPrime-compatible XML."""
        envelope = ET.Element("ENVELOPE")
        header = ET.SubElement(envelope, "HEADER")
        ET.SubElement(header, "TALLYREQUEST").text = "Import Data"

        body = ET.SubElement(envelope, "BODY")
        import_data = ET.SubElement(body, "IMPORTDATA")
        request_desc = ET.SubElement(import_data, "REQUESTDESC")
        ET.SubElement(request_desc, "REPORTNAME").text = "Compliance Audit"

        request_data = ET.SubElement(import_data, "REQUESTDATA")

        for result in audit_results:
            voucher = ET.SubElement(request_data, "TALLYMESSAGE")
            entry = ET.SubElement(voucher, "COMPLIANCEENTRY")
            ET.SubElement(entry, "CHECKID").text = str(_safe_get(result, "check_id", ""))
            ET.SubElement(entry, "FOCUS").text = str(_safe_get(result, "focus", ""))
            ET.SubElement(entry, "STATUS").text = str(_safe_get(result, "compliance_status", ""))
            ET.SubElement(entry, "VIOLATION").text = str(_safe_get(result, "violation_details", ""))
            ET.SubElement(entry, "EVIDENCE").text = str(_safe_get(result, "evidence", ""))
            ET.SubElement(entry, "REMEDIATION").text = str(_safe_get(result, "suggested_amendment", ""))

        buffer = BytesIO()
        tree = ET.ElementTree(envelope)
        tree.write(buffer, encoding="utf-8", xml_declaration=True)
        buffer.seek(0)
        return buffer

    @staticmethod
    def to_zoho_json(audit_results: list) -> BytesIO:
        """Export audit results as Zoho Books-compatible JSON."""
        records = []
        for result in audit_results:
            records.append({
                "check_id": str(_safe_get(result, "check_id", "")),
                "focus": str(_safe_get(result, "focus", "")),
                "status": str(_safe_get(result, "compliance_status", "")),
                "violation": str(_safe_get(result, "violation_details", "")),
                "evidence": str(_safe_get(result, "evidence", "")),
                "remediation": str(_safe_get(result, "suggested_amendment", "")),
            })

        output = {"compliance_records": records}
        buffer = BytesIO(json.dumps(output, indent=2).encode("utf-8"))
        buffer.seek(0)
        return buffer
