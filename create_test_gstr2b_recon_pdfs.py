"""
Generate realistic test PDFs for GSTR-2B vs Purchase Register Reconciliation.

Creates two PDFs:
  1. test_gstr2b_jan2026.pdf   -- GSTR-2B statement (govt portal download style)
  2. test_purchase_register_jan2026.pdf -- Purchase register (Tally/accounting style)

Scenarios covered (10 invoices total spread across both files):
  [OK] Matched (4 invoices)        -- same GSTIN + invoice + amounts in both
  [!!]  Value Mismatch (2 invoices) -- same invoice, different taxable/tax amounts
  [IN] Missing in Books (2)        -- present in GSTR-2B only -> ITC unclaimed
  [OUT] Missing in GSTR-2B (2)      -- present in purchase register only -> ITC at risk
"""

from fpdf import FPDF


class TablePDF(FPDF):
    """PDF with proper bordered tables for PyMuPDF extraction."""

    def header_block(self, title: str, subtitle: str):
        self.set_font("Helvetica", "B", 14)
        self.cell(0, 10, title, ln=True, align="C")
        self.set_font("Helvetica", "", 10)
        self.cell(0, 6, subtitle, ln=True, align="C")
        self.ln(6)

    def table_header(self, col_widths, headers):
        self.set_font("Helvetica", "B", 8)
        self.set_fill_color(220, 220, 220)
        for w, h in zip(col_widths, headers):
            self.cell(w, 7, h, border=1, fill=True, align="C")
        self.ln()

    def table_row(self, col_widths, values, aligns=None):
        self.set_font("Helvetica", "", 8)
        if aligns is None:
            aligns = ["C"] * len(values)
        for w, v, a in zip(col_widths, values, aligns):
            self.cell(w, 6, str(v), border=1, align=a)
        self.ln()


# ---------------------------------------------------------------------------
# DATA -- designed for specific reconciliation outcomes
# ---------------------------------------------------------------------------

# GSTR-2B invoices (8 invoices -- 4 matched, 2 mismatch, 2 missing-in-books)
GSTR2B_DATA = [
    # --- MATCHED (exact same in both files) ---
    # 1. Intra-state B2B -- CGST+SGST
    ("29AABCU9603R1Z5", "INV-2026-001", "05-01-2026", "1,00,000.00", "0.00", "9,000.00", "9,000.00"),
    # 2. Inter-state B2B -- IGST
    ("07AAACR5055K1Z1", "GST/26/0042",  "10-01-2026", "2,50,000.00", "45,000.00", "0.00", "0.00"),
    # 3. Small value intra-state
    ("27AADCB2230M1Z3", "BL-0078",      "15-01-2026", "35,000.00", "0.00", "3,150.00", "3,150.00"),
    # 4. Service invoice inter-state
    ("06AAGCS2345N1Z8", "SRV-JAN-009",  "22-01-2026", "75,000.00", "13,500.00", "0.00", "0.00"),

    # --- VALUE MISMATCH (in both files, but amounts differ) ---
    # 5. Taxable value differs (supplier rounded differently)
    ("33AABCT1234Q1Z9", "TN-2026-112",  "08-01-2026", "1,48,500.00", "0.00", "13,365.00", "13,365.00"),
    # 6. Tax amount differs (rate dispute -- supplier charged 18%, books have 12%)
    ("09AADCF5612P1Z7", "UP/INV/0201",  "18-01-2026", "60,000.00", "10,800.00", "0.00", "0.00"),

    # --- MISSING IN BOOKS (in GSTR-2B only -- ITC available but unclaimed) ---
    # 7. Purchase not yet recorded in books
    ("36AABCS7890R1Z2", "TS-5501",      "12-01-2026", "42,000.00", "0.00", "3,780.00", "3,780.00"),
    # 8. Credit note not recorded
    ("19AABCW3344K1Z6", "WB/CN/026",    "25-01-2026", "18,000.00", "3,240.00", "0.00", "0.00"),
]

# Purchase Register invoices (8 invoices -- 4 matched, 2 mismatch, 2 missing-in-gstr2b)
PURCHASE_DATA = [
    # --- MATCHED (same as GSTR-2B rows 1-4) ---
    ("29AABCU9603R1Z5", "INV-2026-001", "05-01-2026", "1,00,000.00", "0.00", "9,000.00", "9,000.00"),
    ("07AAACR5055K1Z1", "GST/26/0042",  "10-01-2026", "2,50,000.00", "45,000.00", "0.00", "0.00"),
    ("27AADCB2230M1Z3", "BL-0078",      "15-01-2026", "35,000.00", "0.00", "3,150.00", "3,150.00"),
    ("06AAGCS2345N1Z8", "SRV-JAN-009",  "22-01-2026", "75,000.00", "13,500.00", "0.00", "0.00"),

    # --- VALUE MISMATCH (amounts differ from GSTR-2B) ---
    # 5. Books have 1,48,000 instead of 1,48,500 (Rs 500 taxable diff)
    ("33AABCT1234Q1Z9", "TN-2026-112",  "08-01-2026", "1,48,000.00", "0.00", "13,320.00", "13,320.00"),
    # 6. Books have 12% IGST (7,200) instead of 18% (10,800)
    ("09AADCF5612P1Z7", "UP/INV/0201",  "18-01-2026", "60,000.00", "7,200.00", "0.00", "0.00"),

    # --- MISSING IN GSTR-2B (in books only -- ITC at risk) ---
    # 7. Supplier hasn't filed their return yet
    ("32AABCK6677L1Z4", "KL-INV-3302",  "20-01-2026", "55,000.00", "0.00", "4,950.00", "4,950.00"),
    # 8. Invoice from unregistered supplier wrongly claimed
    ("21AABCM8899N1Z1", "OR/2026/088",  "28-01-2026", "22,000.00", "3,960.00", "0.00", "0.00"),
]


def create_gstr2b_pdf(filepath: str):
    pdf = TablePDF(orientation="L", format="A4")
    pdf.add_page()

    pdf.header_block(
        "GSTR-2B - Auto-drafted ITC Statement",
        "GSTIN: 29AABCU9603R1Z5 | Period: January 2026 | Generated: 10-Feb-2026"
    )

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 7, "Part A - B2B Invoices (Supplies from registered persons)", ln=True)
    pdf.ln(2)

    headers = ["Supplier GSTIN", "Invoice No", "Invoice Date", "Taxable Value", "IGST", "CGST", "SGST"]
    widths = [42, 35, 28, 40, 30, 30, 30]
    aligns = ["C", "C", "C", "R", "R", "R", "R"]

    pdf.table_header(widths, headers)
    for row in GSTR2B_DATA:
        pdf.table_row(widths, row, aligns)

    # Totals row
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(0, 6, "Total invoices: 8  |  Total Taxable: Rs 7,28,500  |  Total Tax: Rs 1,24,230", ln=True)

    pdf.ln(8)
    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(0, 5, "Note: This is a system-generated statement from the GST portal. Verify all entries against your books.", ln=True)
    pdf.cell(0, 5, "ITC can only be claimed for invoices appearing in GSTR-2B where the supplier has filed GSTR-1.", ln=True)

    pdf.output(filepath)
    print(f"Created: {filepath}")


def create_purchase_register_pdf(filepath: str):
    pdf = TablePDF(orientation="L", format="A4")
    pdf.add_page()

    pdf.header_block(
        "Purchase Register - January 2026",
        "Company: ABC Enterprises | GSTIN: 29AABCU9603R1Z5 | Printed from Tally ERP"
    )

    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 7, "Inward Supply Details (Tax Invoice wise)", ln=True)
    pdf.ln(2)

    headers = ["Vendor GSTIN", "Bill No", "Bill Date", "Taxable Value", "IGST", "CGST", "SGST"]
    widths = [42, 35, 28, 40, 30, 30, 30]
    aligns = ["C", "C", "C", "R", "R", "R", "R"]

    pdf.table_header(widths, headers)
    for row in PURCHASE_DATA:
        pdf.table_row(widths, row, aligns)

    # Totals
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 8)
    pdf.cell(0, 6, "Total invoices: 8  |  Total Taxable: Rs 7,45,000  |  Total Tax: Rs 1,04,250", ln=True)

    pdf.ln(8)
    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(0, 5, "Purchase register extracted from Tally ERP 9 / Tally Prime.", ln=True)

    pdf.output(filepath)
    print(f"Created: {filepath}")


if __name__ == "__main__":
    create_gstr2b_pdf("test_gstr2b_jan2026.pdf")
    create_purchase_register_pdf("test_purchase_register_jan2026.pdf")
    print("\nBoth test PDFs created successfully!")
    print("\n" + "=" * 80)
    print("EXPECTED RECONCILIATION OUTPUT")
    print("=" * 80)

    print("""
Period: 2026-01

SUMMARY:
  Total GSTR-2B invoices : 8
  Total Purchase invoices: 8
  Matched                : 4
  Value Mismatch         : 2
  Missing in Books       : 2  (in GSTR-2B but NOT in purchase register)
  Missing in GSTR-2B     : 2  (in purchase register but NOT in GSTR-2B)

MATCHED INVOICES (4):
  1. 29AABCU9603R1Z5 | INV-2026-001 | Rs 1,00,000 | Tax Rs 18,000 (CGST+SGST)
  2. 07AAACR5055K1Z1 | GST/26/0042  | Rs 2,50,000 | Tax Rs 45,000 (IGST)
  3. 27AADCB2230M1Z3 | BL-0078      | Rs 35,000   | Tax Rs 6,300  (CGST+SGST)
  4. 06AAGCS2345N1Z8 | SRV-JAN-009  | Rs 75,000   | Tax Rs 13,500 (IGST)

VALUE MISMATCH (2):
  5. 33AABCT1234Q1Z9 | TN-2026-112
     GSTR-2B : Taxable Rs 1,48,500 | Tax Rs 26,730 (CGST 13,365 + SGST 13,365)
     Books   : Taxable Rs 1,48,000 | Tax Rs 26,640 (CGST 13,320 + SGST 13,320)
     Diff    : Taxable Rs 500      | Tax Rs 90
     -> Supplier shows higher value -- verify credit note or price negotiation

  6. 09AADCF5612P1Z7 | UP/INV/0201
     GSTR-2B : Taxable Rs 60,000 | Tax Rs 10,800 (IGST 18%)
     Books   : Taxable Rs 60,000 | Tax Rs  7,200 (IGST 12%)
     Diff    : Taxable Rs 0      | Tax Rs 3,600
     -> Tax rate mismatch -- books have 12% but supplier charged 18%

MISSING IN BOOKS (2) -- ITC available but unclaimed:
  7. 36AABCS7890R1Z2 | TS-5501      | Rs 42,000 | Tax Rs 7,560
     -> Purchase not yet recorded. Book this invoice to claim ITC.
  8. 19AABCW3344K1Z6 | WB/CN/026    | Rs 18,000 | Tax Rs 3,240
     -> Credit note not recorded. Book to claim ITC.

MISSING IN GSTR-2B (2) -- ITC AT RISK:
  7. 32AABCK6677L1Z4 | KL-INV-3302  | Rs 55,000 | Tax Rs 9,900
     -> Supplier hasn't filed GSTR-1. Follow up to avoid ITC reversal.
  8. 21AABCM8899N1Z1 | OR/2026/088  | Rs 22,000 | Tax Rs 3,960
     -> Invoice not in GSTR-2B. Verify supplier registration and filing.

ITC SUMMARY:
  Total ITC (Matched)          : Rs 82,800.00
  ITC Available (unclaimed)    : Rs 10,800.00  <-- book these invoices
  ITC at Risk                  : Rs 13,860.00  <-- follow up with suppliers
  ITC Mismatch Amount          : Rs  3,690.00  <-- resolve discrepancies
""")
