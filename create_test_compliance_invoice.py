"""Generate a reproducible GST test invoice PDF with deliberate violations.

Maps to all 7 checks in gst_blueprint.json — see expected_answers.md for details.
Usage: python create_test_compliance_invoice.py
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT


def create_invoice():
    filename = "test_compliance_invoice.pdf"
    doc = SimpleDocTemplate(
        filename,
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("Title2", parent=styles["Title"], fontSize=14, spaceAfter=2)
    subtitle_style = ParagraphStyle("Sub", parent=styles["Normal"], fontSize=9, alignment=TA_CENTER, spaceAfter=4)
    normal = styles["Normal"]
    small = ParagraphStyle("Small", parent=normal, fontSize=8, leading=10)
    bold_small = ParagraphStyle("BoldSmall", parent=small, fontName="Helvetica-Bold")
    right_small = ParagraphStyle("RightSmall", parent=small, alignment=TA_RIGHT)
    note_style = ParagraphStyle("Note", parent=small, textColor=colors.red, fontSize=7.5)

    elements = []

    # --- Header ---
    elements.append(Paragraph("TAX INVOICE", title_style))
    elements.append(Paragraph("(Under Section 31 of the CGST Act, 2017 read with Rule 46 of the CGST Rules, 2017)", subtitle_style))
    elements.append(HRFlowable(width="100%", thickness=1, color=colors.black))
    elements.append(Spacer(1, 4 * mm))

    # --- Supplier / Buyer Details ---
    supplier_buyer = [
        [
            Paragraph("<b>Supplier Details</b>", bold_small),
            Paragraph("<b>Recipient Details</b>", bold_small),
        ],
        [
            Paragraph(
                "Pinnacle Hospitality Services Pvt Ltd<br/>"
                "No. 42, MG Road, Bengaluru, Karnataka - 560001<br/>"
                "GSTIN: 29AAECP4321R1ZK<br/>"
                "PAN: AAECP4321R<br/>"
                "State: Karnataka (29)<br/>"
                "<b>MSME Registered: Yes (Udyam No: UDYAM-KA-01-0012345)</b>",
                small,
            ),
            Paragraph(
                "Metro Corp Ltd<br/>"
                "Brigade Gateway, Rajajinagar, Bengaluru, Karnataka - 560055<br/>"
                "GSTIN: 29AADCM5678Q1Z3<br/>"
                "PAN: AADCM5678Q<br/>"
                "State: Karnataka (29)",
                small,
            ),
        ],
    ]
    t = Table(supplier_buyer, colWidths=["50%", "50%"])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.95)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 4 * mm))

    # --- Invoice Metadata ---
    meta = [
        ["Invoice No:", "PHS/2025-26/0847", "Invoice Date:", "12-Feb-2026"],
        ["Place of Supply:", "Karnataka (29)", "Reverse Charge:", "No"],
        ["E-Invoice IRN:", "Present", "QR Code:", "NOT PRINTED"],
        ["IRP Ack No:", "NOT AVAILABLE", "IRP Ack Date:", "NOT AVAILABLE"],
    ]
    mt = Table(meta, colWidths=["18%", "32%", "18%", "32%"])
    mt.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    elements.append(mt)
    elements.append(Spacer(1, 4 * mm))

    # --- Line Items (deliberately missing HSN/SAC) ---
    items_header = ["#", "Description of Service", "HSN/SAC", "Qty", "Rate (Rs)", "Amount (Rs)", "CGST 9%", "SGST 9%", "Total (Rs)"]
    items_data = [
        items_header,
        ["1", "Corporate Club Membership\n(Annual premium membership — Prestige Club, Bengaluru)", "NOT PROVIDED", "1", "60,000.00", "60,000.00", "5,400.00", "5,400.00", "70,800.00"],
        ["2", "Outdoor Catering Services\n(Corporate event catering — 150 pax, 3-course meal)", "NOT PROVIDED", "1", "55,000.00", "55,000.00", "4,950.00", "4,950.00", "64,900.00"],
        ["3", "Health & Wellness Consultation\n(Employee wellness program — on-site health screening)", "NOT PROVIDED", "1", "35,000.00", "35,000.00", "3,150.00", "3,150.00", "41,300.00"],
    ]
    totals_rows = [
        ["", "", "", "", "Subtotal:", "1,50,000.00", "13,500.00", "13,500.00", "1,77,000.00"],
        ["", "", "", "", "CGST @ 9%:", "", "13,500.00", "", ""],
        ["", "", "", "", "SGST @ 9%:", "", "", "13,500.00", ""],
        ["", "", "", "", "Grand Total:", "", "", "", "1,77,000.00"],
    ]
    all_rows = items_data + totals_rows

    col_widths = [18, 145, 55, 25, 55, 60, 50, 50, 55]
    lt = Table(all_rows, colWidths=col_widths)
    lt.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, colors.black),
        ("INNERGRID", (0, 0), (-1, len(items_data) - 1), 0.25, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.85, 0.85, 0.9)),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        # Total rows styling
        ("LINEABOVE", (4, len(items_data)), (-1, len(items_data)), 1, colors.black),
        ("FONTNAME", (4, len(items_data)), (4, -1), "Helvetica-Bold"),
        ("FONTNAME", (4, -1), (-1, -1), "Helvetica-Bold"),
    ]))
    elements.append(lt)
    elements.append(Spacer(1, 4 * mm))

    # --- ITC Eligibility Note ---
    elements.append(Paragraph("<b>ITC Eligibility Note:</b>", bold_small))
    elements.append(Paragraph(
        "All three services on this invoice fall under Section 17(5) of the CGST Act — "
        "ITC is NOT eligible. Club membership [17(5)(b)(i)], outdoor catering [17(5)(b)(ii)], "
        "and health services [17(5)(b)(iii)] are blocked categories. "
        "Total ITC blocked: Rs 27,000.00 (CGST Rs 13,500 + SGST Rs 13,500).",
        note_style,
    ))
    elements.append(Spacer(1, 3 * mm))

    # --- GSTR-2B Note ---
    elements.append(Paragraph("<b>GSTR-2B Status:</b>", bold_small))
    elements.append(Paragraph(
        "This invoice has NOT been reflected in GSTR-2B for the current filing period. "
        "Recipient should verify GSTR-2B before considering any ITC claim.",
        note_style,
    ))
    elements.append(Spacer(1, 3 * mm))

    # --- MSME Payment Terms ---
    elements.append(Paragraph("<b>Payment Terms (MSME Vendor):</b>", bold_small))
    elements.append(Paragraph(
        "Pinnacle Hospitality Services Pvt Ltd is a registered MSME (Udyam No: UDYAM-KA-01-0012345). "
        "Payment due within 50 days from invoice date (Due Date: 03-Apr-2026). "
        "Note: Section 43B(h) of the Income Tax Act mandates payment within 45 days for MSME vendors "
        "with a written agreement. Payment beyond 45 days (i.e., after 29-Mar-2026) will result in "
        "disallowance of the expense as a deduction for the buyer in FY 2025-26.",
        small,
    ))
    elements.append(Spacer(1, 3 * mm))

    # --- Amount in Words ---
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    elements.append(Paragraph(
        "<b>Amount in Words:</b> Indian Rupees One Lakh Seventy-Seven Thousand Only",
        small,
    ))
    elements.append(Spacer(1, 3 * mm))

    # --- Bank Details ---
    bank_data = [
        ["Bank Name:", "HDFC Bank, MG Road Branch, Bengaluru"],
        ["Account No:", "50100123456789"],
        ["IFSC:", "HDFC0001234"],
    ]
    bt = Table(bank_data, colWidths=["20%", "80%"])
    bt.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    elements.append(bt)
    elements.append(Spacer(1, 4 * mm))

    # --- Signature (deliberately absent) ---
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    elements.append(Paragraph(
        "Note: Signature is not mandatory for e-invoices generated through IRP. "
        "However, this invoice does NOT contain a valid IRN, IRP acknowledgement, "
        "or QR code — therefore the signature exemption does not apply.",
        note_style,
    ))
    elements.append(Spacer(1, 2 * mm))
    elements.append(Paragraph(
        "Authorised Signatory: _____________________ (NOT SIGNED)",
        right_small,
    ))

    # --- Footer ---
    elements.append(Spacer(1, 6 * mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    elements.append(Paragraph(
        "This is a computer-generated invoice for compliance testing purposes. "
        "Generated by Legal AI Expert test suite.",
        ParagraphStyle("Footer", parent=small, fontSize=6.5, textColor=colors.grey, alignment=TA_CENTER),
    ))

    doc.build(elements)
    print(f"Created: {filename}")
    return filename


if __name__ == "__main__":
    create_invoice()
