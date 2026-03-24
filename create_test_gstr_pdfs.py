"""Generate realistic GSTR-1 and GSTR-3B monthly PDFs for FY 2025-26 testing.

Creates 12 GSTR-1 + 12 GSTR-3B PDFs in test_gstr_pdfs/ directory.
Includes deliberate mismatches between GSTR-1 and GSTR-3B for specific months
to trigger reconciliation flags.
"""
import os
from fpdf import FPDF

OUTPUT_DIR = "test_gstr_pdfs"
GSTIN = "29AABCU9603R1ZM"  # Karnataka state code 29
LEGAL_NAME = "M/s Sunrise Traders"
TRADE_NAME = "Sunrise Traders"

MONTHS = [
    ("Apr", "2025", "04/2025"),
    ("May", "2025", "05/2025"),
    ("Jun", "2025", "06/2025"),
    ("Jul", "2025", "07/2025"),
    ("Aug", "2025", "08/2025"),
    ("Sep", "2025", "09/2025"),
    ("Oct", "2025", "10/2025"),
    ("Nov", "2025", "11/2025"),
    ("Dec", "2025", "12/2025"),
    ("Jan", "2026", "01/2026"),
    ("Feb", "2026", "02/2026"),
    ("Mar", "2026", "03/2026"),
]

# Monthly data - realistic for a medium business
# (b2b, b2c, exempt, igst, cgst, sgst, cess, cdn, amendments)
GSTR1_DATA = [
    # Apr: normal
    {"b2b": 680000, "b2c": 120000, "exempt": 15000, "igst": 48000, "cgst": 63000, "sgst": 63000, "cess": 0, "cdn": -5000, "amend": 0},
    # May: slightly higher
    {"b2b": 720000, "b2c": 130000, "exempt": 12000, "igst": 51000, "cgst": 67500, "sgst": 67500, "cess": 0, "cdn": -3000, "amend": 0},
    # Jun: deliberate mismatch - GSTR-1 shows 850k total but GSTR-3B will show 835k
    {"b2b": 710000, "b2c": 140000, "exempt": 18000, "igst": 51000, "cgst": 68000, "sgst": 68000, "cess": 0, "cdn": -4000, "amend": 0},
    # Jul: normal
    {"b2b": 690000, "b2c": 125000, "exempt": 14000, "igst": 49000, "cgst": 64500, "sgst": 64500, "cess": 0, "cdn": -2000, "amend": 0},
    # Aug: normal
    {"b2b": 750000, "b2c": 145000, "exempt": 16000, "igst": 53500, "cgst": 71000, "sgst": 71000, "cess": 0, "cdn": -6000, "amend": 0},
    # Sep: quarter-end, higher
    {"b2b": 820000, "b2c": 160000, "exempt": 20000, "igst": 58800, "cgst": 78000, "sgst": 78000, "cess": 0, "cdn": -8000, "amend": 2000},
    # Oct: festival season, deliberate mismatch - GSTR-1 higher by ~25k
    {"b2b": 950000, "b2c": 200000, "exempt": 25000, "igst": 69000, "cgst": 92000, "sgst": 92000, "cess": 0, "cdn": -10000, "amend": 0},
    # Nov: normal
    {"b2b": 780000, "b2c": 150000, "exempt": 17000, "igst": 55800, "cgst": 74000, "sgst": 74000, "cess": 0, "cdn": -5000, "amend": 0},
    # Dec: year-end
    {"b2b": 830000, "b2c": 155000, "exempt": 19000, "igst": 59100, "cgst": 78500, "sgst": 78500, "cess": 0, "cdn": -7000, "amend": 3000},
    # Jan: normal
    {"b2b": 700000, "b2c": 135000, "exempt": 13000, "igst": 50100, "cgst": 66500, "sgst": 66500, "cess": 0, "cdn": -4000, "amend": 0},
    # Feb: normal
    {"b2b": 730000, "b2c": 140000, "exempt": 15000, "igst": 52200, "cgst": 69500, "sgst": 69500, "cess": 0, "cdn": -3500, "amend": 0},
    # Mar: FY-end, higher + deliberate tax mismatch
    {"b2b": 880000, "b2c": 170000, "exempt": 22000, "igst": 63000, "cgst": 84000, "sgst": 84000, "cess": 0, "cdn": -9000, "amend": 5000},
]

# GSTR-3B data - mostly matches GSTR-1 but with deliberate discrepancies in Jun, Oct, Mar
GSTR3B_DATA = []
for i, g1 in enumerate(GSTR1_DATA):
    total = g1["b2b"] + g1["b2c"]
    g3b = {
        "total_taxable": total,
        "exempt": g1["exempt"],
        "igst": g1["igst"],
        "cgst": g1["cgst"],
        "sgst": g1["sgst"],
        "cess": g1["cess"],
        # ITC data (realistic)
        "itc_igst": int(g1["igst"] * 0.55),
        "itc_cgst": int(g1["cgst"] * 0.60),
        "itc_sgst": int(g1["sgst"] * 0.60),
        "itc_cess": 0,
        "itc_reversed": int(total * 0.002),  # ~0.2% reversal
        "tax_paid_cash": 0,
        "tax_paid_itc": 0,
    }
    # Calculate tax paid
    total_tax = g3b["igst"] + g3b["cgst"] + g3b["sgst"]
    total_itc = g3b["itc_igst"] + g3b["itc_cgst"] + g3b["itc_sgst"] - g3b["itc_reversed"]
    g3b["tax_paid_itc"] = min(total_itc, total_tax)
    g3b["tax_paid_cash"] = max(0, total_tax - total_itc)

    GSTR3B_DATA.append(g3b)

# Apply deliberate mismatches
# Jun (index 2): GSTR-3B turnover lower by ~15k
GSTR3B_DATA[2]["total_taxable"] -= 15000
GSTR3B_DATA[2]["cgst"] -= 1350
GSTR3B_DATA[2]["sgst"] -= 1350

# Oct (index 6): GSTR-3B turnover lower by ~25k (festival season mismatch)
GSTR3B_DATA[6]["total_taxable"] -= 25000
GSTR3B_DATA[6]["igst"] -= 2250
GSTR3B_DATA[6]["cgst"] -= 1125
GSTR3B_DATA[6]["sgst"] -= 1125

# Mar (index 11): GSTR-3B has higher tax (over-reported by ~2k in CGST/SGST)
GSTR3B_DATA[11]["cgst"] += 2000
GSTR3B_DATA[11]["sgst"] += 2000


def _fmt(val):
    """Format Indian currency with commas."""
    if val == 0:
        return "0.00"
    s = f"{abs(val):,.2f}"
    return f"-{s}" if val < 0 else s


def create_gstr1_pdf(month_name, year, period, data, output_path):
    """Generate a realistic GSTR-1 monthly return PDF."""
    pdf = FPDF()
    pdf.add_page()

    total_taxable = data["b2b"] + data["b2c"]

    # Header
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Form GSTR-1", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, "Statement of Outward Supplies", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.cell(0, 6, "[See Rule 59(1)]", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(4)

    # Taxpayer details
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "1. GSTIN / UIN of the Taxpayer", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, f"   {GSTIN}", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "2. Legal Name of the Registered Person", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, f"   {LEGAL_NAME}", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, f"3. Tax Period: {month_name} {year}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Table 4: Taxable outward supplies (B2B)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 7, "Table 4 - Taxable Outward Supplies to Registered Persons (B2B)", new_x="LMARGIN", new_y="NEXT")

    _draw_table(pdf, [
        ["Description", "Taxable Value", "IGST", "CGST", "SGST", "Cess"],
        ["B2B Outward Supplies", _fmt(data["b2b"]), _fmt(data["igst"]), _fmt(int(data["cgst"]*0.7)), _fmt(int(data["sgst"]*0.7)), "0.00"],
    ])
    pdf.ln(3)

    # Table 5: B2C
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 7, "Table 5 - Taxable Outward Inter-State Supplies (B2C Large)", new_x="LMARGIN", new_y="NEXT")

    _draw_table(pdf, [
        ["Description", "Taxable Value", "IGST", "CGST", "SGST", "Cess"],
        ["B2C Outward Supplies", _fmt(data["b2c"]), _fmt(int(data["igst"]*0.3)), _fmt(int(data["cgst"]*0.3)), _fmt(int(data["sgst"]*0.3)), "0.00"],
    ])
    pdf.ln(3)

    # Table 8: Nil rated
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 7, "Table 8 - Nil Rated, Exempted and Non-GST Outward Supplies", new_x="LMARGIN", new_y="NEXT")

    _draw_table(pdf, [
        ["Description", "Value"],
        ["Nil Rated / Exempted / Non-GST Supplies", _fmt(data["exempt"])],
    ])
    pdf.ln(3)

    # Summary section
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 7, "Summary of Outward Supplies", new_x="LMARGIN", new_y="NEXT")

    _draw_table(pdf, [
        ["Particulars", "Taxable Value", "IGST", "CGST", "SGST", "Cess"],
        ["Total Taxable Outward Supplies", _fmt(total_taxable), _fmt(data["igst"]), _fmt(data["cgst"]), _fmt(data["sgst"]), _fmt(data["cess"])],
        ["Credit/Debit Notes (Net)", _fmt(data["cdn"]), "", "", "", ""],
        ["Amendments (Net)", _fmt(data["amend"]), "", "", "", ""],
        ["Exempt/Nil/Non-GST", _fmt(data["exempt"]), "-", "-", "-", "-"],
    ])
    pdf.ln(5)

    # Footer
    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(0, 5, f"Generated from GST Portal | GSTIN: {GSTIN} | Period: {month_name} {year}", new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.output(output_path)


def create_gstr3b_pdf(month_name, year, period, data, output_path):
    """Generate a realistic GSTR-3B monthly return PDF."""
    pdf = FPDF()
    pdf.add_page()

    # Header
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "Form GSTR-3B", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, "Monthly Return", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.cell(0, 6, "[See Rule 61(5)]", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(4)

    # Taxpayer details
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, f"GSTIN: {GSTIN}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Legal Name: {LEGAL_NAME}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Tax Period: {month_name} {year}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    total_tax = data["igst"] + data["cgst"] + data["sgst"] + data["cess"]

    # Table 3.1: Outward supplies
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 7, "3.1 Details of Outward Supplies and Inward Supplies liable to Reverse Charge", new_x="LMARGIN", new_y="NEXT")

    _draw_table(pdf, [
        ["Nature of Supplies", "Taxable Value", "IGST", "CGST", "SGST/UTGST", "Cess"],
        ["(a) Outward taxable supplies (other than zero rated, nil rated and exempted)", _fmt(data["total_taxable"]), _fmt(data["igst"]), _fmt(data["cgst"]), _fmt(data["sgst"]), _fmt(data["cess"])],
        ["(b) Outward taxable supplies (zero rated)", "0.00", "0.00", "0.00", "0.00", "0.00"],
        ["(c) Other outward supplies (nil rated, exempted)", _fmt(data["exempt"]), "0.00", "0.00", "0.00", "0.00"],
        ["(d) Inward supplies (liable to reverse charge)", "0.00", "0.00", "0.00", "0.00", "0.00"],
        ["(e) Non-GST outward supplies", "0.00", "0.00", "0.00", "0.00", "0.00"],
    ])
    pdf.ln(3)

    # Table 4: ITC
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 7, "4. Eligible ITC", new_x="LMARGIN", new_y="NEXT")

    _draw_table(pdf, [
        ["Details", "IGST", "CGST", "SGST/UTGST", "Cess"],
        ["(A) ITC Available (whether in full or part)", _fmt(data["itc_igst"]), _fmt(data["itc_cgst"]), _fmt(data["itc_sgst"]), _fmt(data["itc_cess"])],
        ["(B) ITC Reversed", _fmt(int(data["itc_reversed"]*0.3)), _fmt(int(data["itc_reversed"]*0.35)), _fmt(int(data["itc_reversed"]*0.35)), "0.00"],
        ["(C) Net ITC Available (A)-(B)", _fmt(data["itc_igst"] - int(data["itc_reversed"]*0.3)), _fmt(data["itc_cgst"] - int(data["itc_reversed"]*0.35)), _fmt(data["itc_sgst"] - int(data["itc_reversed"]*0.35)), "0.00"],
    ])
    pdf.ln(3)

    # Table 5: Exempt supplies
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 7, "5. Values of Exempt, Nil-Rated and Non-GST Inward Supplies", new_x="LMARGIN", new_y="NEXT")

    _draw_table(pdf, [
        ["Nature of Supplies", "Inter-State", "Intra-State"],
        ["Exempt / Nil Rated", "0.00", _fmt(data["exempt"])],
        ["Non-GST", "0.00", "0.00"],
    ])
    pdf.ln(3)

    # Table 6.1: Tax payment
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 7, "6.1 Payment of Tax", new_x="LMARGIN", new_y="NEXT")

    _draw_table(pdf, [
        ["Description", "Tax Payable", "Paid through ITC", "Paid in Cash", "Interest", "Late Fee"],
        ["IGST", _fmt(data["igst"]), _fmt(min(data["itc_igst"], data["igst"])), _fmt(max(0, data["igst"] - data["itc_igst"])), "0.00", "0.00"],
        ["CGST", _fmt(data["cgst"]), _fmt(min(data["itc_cgst"], data["cgst"])), _fmt(max(0, data["cgst"] - data["itc_cgst"])), "0.00", "0.00"],
        ["SGST/UTGST", _fmt(data["sgst"]), _fmt(min(data["itc_sgst"], data["sgst"])), _fmt(max(0, data["sgst"] - data["itc_sgst"])), "0.00", "0.00"],
        ["Cess", _fmt(data["cess"]), "0.00", "0.00", "0.00", "0.00"],
    ])
    pdf.ln(3)

    # Summary
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, f"Total Tax Liability: Rs. {_fmt(total_tax)}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Total Tax Paid through ITC: Rs. {_fmt(data['tax_paid_itc'])}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Total Tax Paid in Cash: Rs. {_fmt(data['tax_paid_cash'])}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # ITC reversed total
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, f"ITC Reversed (4B): Rs. {_fmt(data['itc_reversed'])}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(0, 5, f"Generated from GST Portal | GSTIN: {GSTIN} | Period: {month_name} {year}", new_x="LMARGIN", new_y="NEXT", align="C")

    pdf.output(output_path)


def _draw_table(pdf, rows):
    """Draw a simple table with header row bold."""
    pdf.set_font("Helvetica", "B", 7)
    n_cols = len(rows[0])
    col_w = min(30, int((pdf.w - pdf.l_margin - pdf.r_margin) / n_cols))
    # First column wider for descriptions
    first_w = pdf.w - pdf.l_margin - pdf.r_margin - col_w * (n_cols - 1)

    for ri, row in enumerate(rows):
        if ri == 0:
            pdf.set_font("Helvetica", "B", 7)
            pdf.set_fill_color(230, 230, 230)
        else:
            pdf.set_font("Helvetica", "", 7)
            pdf.set_fill_color(255, 255, 255)

        for ci, cell in enumerate(row):
            w = first_w if ci == 0 else col_w
            # Truncate long text
            display = str(cell)[:50]
            pdf.cell(w, 5, display, border=1, fill=(ri == 0))
        pdf.ln()


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for i, (month_name, year, period) in enumerate(MONTHS):
        # GSTR-1
        g1_path = os.path.join(OUTPUT_DIR, f"GSTR1_{month_name}_{year}.pdf")
        create_gstr1_pdf(month_name, year, period, GSTR1_DATA[i], g1_path)
        g1_total = GSTR1_DATA[i]["b2b"] + GSTR1_DATA[i]["b2c"]
        g1_tax = GSTR1_DATA[i]["igst"] + GSTR1_DATA[i]["cgst"] + GSTR1_DATA[i]["sgst"]

        # GSTR-3B
        g3b_path = os.path.join(OUTPUT_DIR, f"GSTR3B_{month_name}_{year}.pdf")
        create_gstr3b_pdf(month_name, year, period, GSTR3B_DATA[i], g3b_path)
        g3b_total = GSTR3B_DATA[i]["total_taxable"]
        g3b_tax = GSTR3B_DATA[i]["igst"] + GSTR3B_DATA[i]["cgst"] + GSTR3B_DATA[i]["sgst"]

        diff = g1_total - g3b_total
        marker = " ***MISMATCH***" if abs(diff) > 100 else ""
        print(f"{month_name} {year}: GSTR1={g1_total:>10,} tax={g1_tax:>8,} | GSTR3B={g3b_total:>10,} tax={g3b_tax:>8,} | diff={diff:>+8,}{marker}")

    print(f"\nCreated 24 PDFs in {OUTPUT_DIR}/")
    print(f"\nGSTIN for testing: {GSTIN}")
    print(f"Financial Year: 2025-26")
    print(f"Books Turnover (use for books reconciliation): 10500000")

    # Print expected totals
    g1_total_all = sum(d["b2b"] + d["b2c"] for d in GSTR1_DATA)
    g3b_total_all = sum(d["total_taxable"] for d in GSTR3B_DATA)
    g1_tax_all = sum(d["igst"] + d["cgst"] + d["sgst"] for d in GSTR1_DATA)
    g3b_tax_all = sum(d["igst"] + d["cgst"] + d["sgst"] for d in GSTR3B_DATA)

    print(f"\n=== EXPECTED ANNUAL TOTALS ===")
    print(f"GSTR-1 Total Turnover: {g1_total_all:>12,}")
    print(f"GSTR-3B Total Turnover: {g3b_total_all:>12,}")
    print(f"Turnover Diff: {g1_total_all - g3b_total_all:>+12,}")
    print(f"GSTR-1 Total Tax: {g1_tax_all:>12,}")
    print(f"GSTR-3B Total Tax: {g3b_tax_all:>12,}")
    print(f"Tax Diff: {g3b_tax_all - g1_tax_all:>+12,}")
    print(f"\nExpected discrepancies: Jun (turnover -15k), Oct (turnover -25k), Mar (tax +4k)")


if __name__ == "__main__":
    main()
