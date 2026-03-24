"""Generate a realistic Indian bank statement PDF for testing bank analysis feature."""
from fpdf import FPDF

pdf = FPDF()
pdf.add_page()

# Bank header
pdf.set_font("Helvetica", "B", 16)
pdf.cell(0, 10, "HDFC BANK LIMITED", ln=True, align="C")
pdf.set_font("Helvetica", "", 10)
pdf.cell(0, 6, "Statement of Account", ln=True, align="C")
pdf.ln(3)

# Account details
pdf.set_font("Helvetica", "", 9)
pdf.cell(0, 6, "Account No: 50100284736152    |    IFSC: HDFC0001234    |    Branch: MG Road, Bangalore", ln=True)
pdf.cell(0, 6, "Account Holder: M/s Sunrise Traders    |    Account Type: Current Account", ln=True)
pdf.cell(0, 6, "Statement Period: 01-Apr-2025 to 31-Mar-2026", ln=True)
pdf.ln(4)

# Separator line
pdf.set_draw_color(0, 0, 0)
pdf.line(10, pdf.get_y(), 200, pdf.get_y())
pdf.ln(3)

# Table header
pdf.set_font("Helvetica", "B", 8)
cols = ["Date", "Narration", "Chq/Ref No", "Debit", "Credit", "Balance"]
widths = [22, 62, 25, 22, 22, 27]
for c, w in zip(cols, widths):
    pdf.cell(w, 7, c, border=1, align="C")
pdf.ln()

# Transactions designed to trigger various statutory flags
transactions = [
    # Opening balance entry
    ("01/04/2025", "OPENING BALANCE", "", "", "", "10,00,000.00"),
    # Normal NEFT payment
    ("02/04/2025", "NEFT-N123456-VENDOR ABC TRADERS", "N123456", "45,000.00", "", "9,55,000.00"),
    # SEC_269ST_VIOLATION: Cash receipt >= 2,00,000
    ("05/04/2025", "BY CASH DEPOSIT", "SELF", "", "2,50,000.00", "12,05,000.00"),
    # Normal UPI
    ("08/04/2025", "UPI-PHONEPE-OFFICE RENT APR", "UPI789012", "35,000.00", "", "11,70,000.00"),
    # ATM withdrawal
    ("10/04/2025", "ATM CASH WDL-MG ROAD BR", "ATM5543", "50,000.00", "", "11,20,000.00"),
    # SEC_269ST_VIOLATION: Another large cash deposit
    ("15/04/2025", "CASH DEP BY PROPRIETOR", "SELF", "", "3,00,000.00", "14,20,000.00"),
    # ROUND_AMOUNT_OBSERVATION: >= 1L divisible by 50K
    ("20/04/2025", "NEFT-PROPERTY TAX PAYMENT", "N234567", "1,50,000.00", "", "12,70,000.00"),
    # Normal cheque
    ("25/04/2025", "CHQ PAID-543210-SUPPLIER DELTA", "543210", "28,000.00", "", "12,42,000.00"),
    # INTEREST_194A: Interest > 40,000 (cumulative)
    ("01/05/2025", "INTEREST CREDITED Q1", "INT-Q1", "", "42,500.00", "12,84,500.00"),
    # Normal IMPS
    ("05/05/2025", "IMPS-P345678-STAFF SALARY MAY", "P345678", "65,000.00", "", "12,19,500.00"),
    # Large ATM withdrawal contributing to SFT cumulative
    ("10/05/2025", "CASH WDL ATM KORAMANGALA", "ATM6621", "2,00,000.00", "", "10,19,500.00"),
    # SEC_269ST_WARNING: Cash receipt 1-2L range
    ("15/05/2025", "BY CASH-CUSTOMER PAYMENT", "CASH", "", "1,50,000.00", "11,69,500.00"),
    # Normal NACH
    ("01/06/2025", "NACH-LIC PREMIUM-POL123456", "NACH001", "12,500.00", "", "11,57,000.00"),
    # NEFT salary credit
    ("15/06/2025", "NEFT-PARTNER CAPITAL INFUSION", "N456789", "", "75,000.00", "12,32,000.00"),
    # SEC_269ST_VIOLATION: Large cash deposit + SFT cumulative
    ("22/06/2025", "CASH DEPOSIT-COUNTER", "CASH", "", "5,00,000.00", "17,32,000.00"),
    # SUNDAY_TRANSACTION: 29 Jun 2025 is a Sunday + large ATM withdrawal
    ("29/06/2025", "ATM CASH WITHDRAWAL-EMERGENCY", "ATM7789", "3,00,000.00", "", "14,32,000.00"),
    # Normal auto debit
    ("01/07/2025", "AUTO DEBIT-HDFC HOME LOAN EMI", "EMI0045", "52,000.00", "", "13,80,000.00"),
    # ROUND_AMOUNT_OBSERVATION: 5L property advance
    ("15/07/2025", "RTGS-PROPERTY ADVANCE-KUMAR", "R567890", "5,00,000.00", "", "8,80,000.00"),
    # Normal ECS
    ("01/08/2025", "ECS-MUTUAL FUND SIP-AXIS MF", "ECS112", "25,000.00", "", "8,55,000.00"),
    # SEC_269ST_WARNING: Cash receipt approaching limit
    ("20/08/2025", "CASH DEP-SHOP COLLECTION", "CASH", "", "1,20,000.00", "9,75,000.00"),
    # Normal credit
    ("01/09/2025", "NEFT-CUSTOMER INVOICE 4521", "N678901", "", "88,000.00", "10,63,000.00"),
    # Insurance NACH
    ("15/09/2025", "NACH-STAR HEALTH INSURANCE", "NACH002", "18,500.00", "", "10,44,500.00"),
    # Large cash withdrawal pushing SFT cumulative higher
    ("15/10/2025", "CASH WITHDRAWAL-BRANCH COUNTER", "CASH", "4,00,000.00", "", "6,44,500.00"),
    # Normal NEFT
    ("01/11/2025", "NEFT-GST PAYMENT OCT", "N789012", "32,000.00", "", "6,12,500.00"),
    # Q3 interest
    ("01/12/2025", "INTEREST CREDITED Q3", "INT-Q3", "", "38,000.00", "6,50,500.00"),
    # Normal UPI
    ("15/12/2025", "UPI-GPAY-ELECTRICITY BILL DEC", "UPI901234", "8,500.00", "", "6,42,000.00"),
    # Large IMPS payment
    ("15/01/2026", "IMPS-CONTRACTOR FINAL PAYMENT", "P890123", "1,50,000.00", "", "4,92,000.00"),
    # Normal credit
    ("01/02/2026", "NEFT-CLIENT PAYMENT FEB", "N012345", "", "2,25,000.00", "7,17,000.00"),
    # SEC_269ST_VIOLATION: FY-end large cash deposit
    ("01/03/2026", "CASH DEPOSIT-FY CLOSING", "CASH", "", "2,00,000.00", "9,17,000.00"),
    # SEC_40A3_RISK: Cash payment > 10,000 (if mode is cash debit)
    ("15/03/2026", "CASH WDL-VENDOR CASH PAYMENT", "CASH", "85,000.00", "", "8,32,000.00"),
    # Closing
    ("31/03/2026", "NEFT-ADVANCE TAX FY26", "N345678", "1,20,000.00", "", "7,12,000.00"),
]

pdf.set_font("Helvetica", "", 7.5)
for txn in transactions:
    for val, w in zip(txn, widths):
        pdf.cell(w, 6, val, border=1, align="R" if val and val[0].isdigit() and "," in val else "L")
    pdf.ln()

# Footer
pdf.ln(5)
pdf.set_font("Helvetica", "I", 8)
pdf.cell(0, 5, "This is a computer-generated statement and does not require a signature.", ln=True, align="C")
pdf.cell(0, 5, "Please report any discrepancy within 15 days of receipt.", ln=True, align="C")

pdf.output("test_bank_statement.pdf")
print("Created: test_bank_statement.pdf")
print("Transactions: {}".format(len(transactions)))
print()
print("Expected flags to trigger:")
print("  HIGH:   SEC_269ST_VIOLATION (4x cash receipts >= 2L)")
print("  HIGH:   SFT_CASH_DEPOSIT (FY cash deposits ~15.2L >= 10L)")
print("  HIGH:   SFT_CASH_WITHDRAWAL (FY cash withdrawals ~9.35L - may trigger warning)")
print("  HIGH:   INTEREST_194A_THRESHOLD (FY interest = 80,500 > 40K)")
print("  MEDIUM: SEC_269ST_WARNING (2x cash receipts in 1-2L range)")
print("  MEDIUM: SFT_CASH_DEPOSIT_WARNING (crossed 5L early)")
print("  MEDIUM: SFT_CASH_WITHDRAWAL_WARNING (crossed 5L)")
print("  LOW:    ROUND_AMOUNT_OBSERVATION (1.5L, 5L amounts)")
print("  LOW:    SUNDAY_TRANSACTION (29-Jun-2025)")
