"""Generate realistic GSTR-2B and Purchase Register PDFs for testing."""

from fpdf import FPDF
import os

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))


def create_gstr2b_pdf():
    """Create a realistic GSTR-2B PDF as downloaded from GSTN portal."""
    pdf = FPDF(orientation="L", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Header
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "GSTR-2B - Auto-drafted ITC Statement", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, "Return Period: March 2026", ln=True, align="C")
    pdf.cell(0, 6, "GSTIN: 29AADCS1234F1Z9  |  Trade Name: Sample Enterprises Pvt Ltd", ln=True, align="C")
    pdf.cell(0, 6, "Generated on: 14-04-2026  |  Source: GST Portal", ln=True, align="C")
    pdf.ln(5)

    # Section header
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "Part A - ITC Available - B2B Invoices", ln=True)
    pdf.ln(2)

    # Table header
    headers = ["Sl No", "GSTIN of Supplier", "Supplier Name", "Invoice No", "Invoice Date",
               "Taxable Value", "IGST", "CGST", "SGST", "Total Tax", "ITC Avl"]
    col_widths = [12, 38, 45, 35, 25, 28, 22, 22, 22, 22, 16]

    pdf.set_font("Helvetica", "B", 7)
    pdf.set_fill_color(220, 220, 220)
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 7, h, border=1, fill=True, align="C")
    pdf.ln()

    # Data rows - matches the JSON file
    rows = [
        ["1", "29AABCU9603R1Z5", "Acme Technologies Pvt Ltd", "ACM/2025-26/1234", "05-03-2026",
         "1,00,000.00", "0.00", "9,000.00", "9,000.00", "18,000.00", "Yes"],
        ["2", "29AABCU9603R1Z5", "Acme Technologies Pvt Ltd", "ACM/2025-26/1298", "15-03-2026",
         "50,000.00", "0.00", "4,500.00", "4,500.00", "9,000.00", "Yes"],
        ["3", "07AADCB2230M1Z3", "Bright Solutions LLP", "BS-4501", "02-03-2026",
         "2,00,000.00", "36,000.00", "0.00", "0.00", "36,000.00", "Yes"],
        ["4", "07AADCB2230M1Z3", "Bright Solutions LLP", "BS-4567", "20-03-2026",
         "48,000.00", "8,640.00", "0.00", "0.00", "8,640.00", "Yes"],
        ["5", "27AAECR5055K1Z8", "Rajesh Steel Industries", "RSI/INV/2026/0345", "10-03-2026",
         "5,00,000.00", "90,000.00", "0.00", "0.00", "90,000.00", "Yes"],
        ["6", "33AAHCP7654R1Z9", "Premier Packaging Co", "PPC-0089", "08-03-2026",
         "30,000.00", "5,400.00", "0.00", "0.00", "5,400.00", "Yes"],
        ["7", "29AADCN8765P1Z2", "Naveen Logistics", "NL/MAR/001", "12-03-2026",
         "20,000.00", "0.00", "1,800.00", "1,800.00", "3,600.00", "Yes"],
        ["8", "29AAACW4201L1Z6", "Wipro Enterprises Ltd", "WEL-2026-78901", "18-03-2026",
         "3,00,000.00", "0.00", "27,000.00", "27,000.00", "54,000.00", "Yes"],
        ["9", "36AABCT1332L1Z1", "TechServe India Pvt Ltd", "TS/26/MAR/0055", "22-03-2026",
         "1,50,000.00", "27,000.00", "0.00", "0.00", "27,000.00", "No"],
        ["10", "29AABCG5432N1Z7", "Global Print Services", "GPS-3344", "25-03-2026",
         "10,000.00", "0.00", "900.00", "900.00", "1,800.00", "Yes"],
        ["11", "24AABCM6789Q1Z4", "Metro Office Supplies", "MOS/INV/2026/0221", "28-03-2026",
         "60,000.00", "10,800.00", "0.00", "0.00", "10,800.00", "Yes"],
        ["12", "29AADCK1234B1Z0", "Krishna Hardware", "KH-MAR-0056", "14-03-2026",
         "40,000.00", "0.00", "3,600.00", "3,600.00", "7,200.00", "Yes"],
    ]

    pdf.set_font("Helvetica", "", 6.5)
    for row in rows:
        for i, val in enumerate(row):
            align = "R" if i >= 5 and i <= 9 else ("C" if i in [0, 10] else "L")
            pdf.cell(col_widths[i], 6, val, border=1, align=align)
        pdf.ln()

    # Summary
    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 7, "Summary:", ln=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, "Total B2B Invoices: 12", ln=True)
    pdf.cell(0, 6, "Total Taxable Value: Rs 15,08,000.00", ln=True)
    pdf.cell(0, 6, "Total ITC Available (IGST): Rs 1,77,840.00", ln=True)
    pdf.cell(0, 6, "Total ITC Available (CGST): Rs 46,800.00", ln=True)
    pdf.cell(0, 6, "Total ITC Available (SGST): Rs 46,800.00", ln=True)
    pdf.cell(0, 6, "ITC Not Available (Ineligible): Rs 27,000.00 (1 invoice)", ln=True)

    output_path = os.path.join(OUTPUT_DIR, "gstr2b_march2026.pdf")
    pdf.output(output_path)
    print(f"Created: {output_path}")


def create_purchase_register_pdf():
    """Create a realistic Purchase Register PDF as exported from Tally/accounting software."""
    pdf = FPDF(orientation="L", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Header - Tally-style
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Sample Enterprises Pvt Ltd", ln=True, align="C")
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Purchase Register", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, "Period: 01-03-2026 to 31-03-2026", ln=True, align="C")
    pdf.cell(0, 6, "GSTIN: 29AADCS1234F1Z9", ln=True, align="C")
    pdf.ln(5)

    # Table header
    headers = ["Sl No", "Supplier GSTIN", "Supplier Name", "Bill No", "Bill Date",
               "Taxable Value", "IGST", "CGST", "SGST", "Total Tax", "Description"]
    col_widths = [12, 38, 42, 30, 22, 25, 20, 20, 20, 22, 36]

    pdf.set_font("Helvetica", "B", 7)
    pdf.set_fill_color(200, 200, 240)
    for i, h in enumerate(headers):
        pdf.cell(col_widths[i], 7, h, border=1, fill=True, align="C")
    pdf.ln()

    # Data rows - deliberately has mismatches with GSTR-2B
    rows = [
        ["1", "29AABCU9603R1Z5", "Acme Technologies Pvt Ltd", "ACM/2025-26/1234", "05-03-2026",
         "1,00,000.00", "0.00", "9,000.00", "9,000.00", "18,000.00", "IT Equipment"],
        ["2", "29AABCU9603R1Z5", "Acme Technologies Pvt Ltd", "ACM/2025-26/1298", "15-03-2026",
         "50,000.00", "0.00", "4,500.00", "4,500.00", "9,000.00", "AMC"],
        ["3", "07AADCB2230M1Z3", "Bright Solutions LLP", "BS-4501", "02-03-2026",
         "2,00,000.00", "36,000.00", "0.00", "0.00", "36,000.00", "Consulting"],
        # BS-4567: VALUE MISMATCH - books show 45,000 vs 2B shows 48,000
        ["4", "07AADCB2230M1Z3", "Bright Solutions LLP", "BS-4567", "20-03-2026",
         "45,000.00", "8,100.00", "0.00", "0.00", "8,100.00", "Training"],
        # RSI: VALUE MISMATCH - books show 4,90,000 vs 2B shows 5,00,000
        ["5", "27AAECR5055K1Z8", "Rajesh Steel Industries", "RSI/INV/2026/0345", "10-03-2026",
         "4,90,000.00", "88,200.00", "0.00", "0.00", "88,200.00", "Steel"],
        # PPC-89 vs PPC-0089 - INVOICE NUMBER FORMAT DIFFERENCE
        ["6", "33AAHCP7654R1Z9", "Premier Packaging Co", "PPC-89", "08-03-2026",
         "30,000.00", "5,400.00", "0.00", "0.00", "5,400.00", "Packaging"],
        ["7", "29AADCN8765P1Z2", "Naveen Logistics", "NL/MAR/001", "12-03-2026",
         "20,000.00", "0.00", "1,800.00", "1,800.00", "3,600.00", "Freight"],
        ["8", "29AAACW4201L1Z6", "Wipro Enterprises Ltd", "WEL-2026-78901", "18-03-2026",
         "3,00,000.00", "0.00", "27,000.00", "27,000.00", "54,000.00", "Software"],
        ["9", "36AABCT1332L1Z1", "TechServe India Pvt Ltd", "TS/26/MAR/0055", "22-03-2026",
         "1,50,000.00", "27,000.00", "0.00", "0.00", "27,000.00", "Cloud Infra"],
        ["10", "29AABCG5432N1Z7", "Global Print Services", "GPS-3344", "25-03-2026",
         "10,000.00", "0.00", "900.00", "900.00", "1,800.00", "Stationery"],
        # KH/MAR/56 vs KH-MAR-0056 - INVOICE NUMBER FORMAT DIFFERENCE
        ["11", "29AADCK1234B1Z0", "Krishna Hardware", "KH/MAR/56", "14-03-2026",
         "40,000.00", "0.00", "3,600.00", "3,600.00", "7,200.00", "Plumbing"],
        # ONLY IN BOOKS - not in GSTR-2B (supplier hasn't filed)
        ["12", "29AABCD1111E1Z5", "DataFlow Analytics", "DFA/2026/0033", "16-03-2026",
         "75,000.00", "0.00", "6,750.00", "6,750.00", "13,500.00", "Data Platform"],
        ["13", "29AABCE2222F1Z8", "Elite Catering Services", "ECS-1122", "19-03-2026",
         "25,000.00", "0.00", "1,250.00", "1,250.00", "2,500.00", "Catering"],
    ]

    pdf.set_font("Helvetica", "", 6.5)
    for row in rows:
        for i, val in enumerate(row):
            align = "R" if i >= 5 and i <= 9 else ("C" if i == 0 else "L")
            pdf.cell(col_widths[i], 6, val, border=1, align=align)
        pdf.ln()

    # Totals
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 7, "Total Purchase Value: Rs 15,35,000.00  |  Total Tax: Rs 2,74,300.00", ln=True)

    output_path = os.path.join(OUTPUT_DIR, "purchase_register_march2026.pdf")
    pdf.output(output_path)
    print(f"Created: {output_path}")


if __name__ == "__main__":
    create_gstr2b_pdf()
    create_purchase_register_pdf()
    print("\nAll test PDFs generated successfully!")
