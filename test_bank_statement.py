from fpdf import FPDF

  pdf = FPDF()
  pdf.add_page()
  pdf.set_font("Helvetica", "B", 14)
  pdf.cell(0, 10, "HDFC Bank - Account Statement", ln=True, align="C")
  pdf.set_font("Helvetica", "", 10)
  pdf.cell(0, 8, "Account: 12345678901234 | Branch: MG Road", ln=True)
  pdf.cell(0, 8, "Period: 01-Apr-2025 to 31-Mar-2026", ln=True)
  pdf.ln(5)

  # Table header
  pdf.set_font("Helvetica", "B", 9)
  cols = ["Date", "Narration", "Debit", "Credit", "Balance"]
  widths = [25, 75, 25, 25, 30]
  for c, w in zip(cols, widths):
      pdf.cell(w, 8, c, border=1)
  pdf.ln()

  # Transactions designed to trigger flags
  transactions = [
      ("01/04/2025", "NEFT-VENDOR-ABC-PAYMENT", "45,000.00", "", "9,55,000.00"),
      ("05/04/2025", "BY CASH DEPOSIT", "", "2,50,000.00", "12,05,000.00"),       # SEC_269ST_VIOLATION (>=2L cash receipt)
      ("10/04/2025", "CASH WITHDRAWAL ATM", "1,50,000.00", "", "10,55,000.00"),
      ("15/04/2025", "CASH DEP BY SELF", "", "3,00,000.00", "13,55,000.00"),       # SEC_269ST_VIOLATION
      ("20/04/2025", "UPI-RENT-PAYMENT", "50,000.00", "", "13,05,000.00"),         # ROUND_AMOUNT_OBSERVATION
      ("01/05/2025", "INTEREST CREDITED", "", "42,500.00", "13,47,500.00"),        # INTEREST_194A_THRESHOLD (>40K)
      ("10/05/2025", "CASH WDL ATM BRANCH", "2,00,000.00", "", "11,47,500.00"),
      ("15/05/2025", "BY CASH", "", "1,50,000.00", "12,97,500.00"),               # SEC_269ST_WARNING
      ("01/06/2025", "CHQ-543210-SUPPLIER", "15,000.00", "", "12,82,500.00"),
      ("15/06/2025", "NEFT-SALARY-JUNE", "", "75,000.00", "13,57,500.00"),
      ("22/06/2025", "CASH DEPOSIT", "", "5,00,000.00", "18,57,500.00"),           # SEC_269ST_VIOLATION + SFT cumulative
      ("29/06/2025", "ATM CASH WITHDRAWAL", "3,00,000.00", "", "15,57,500.00"),    # Sunday transaction (29 Jun 2025 is Sunday)
      ("01/07/2025", "AUTO DEBIT-EMI-HDFC", "25,000.00", "", "15,32,500.00"),
      ("15/07/2025", "RTGS-PROPERTY-ADVANCE", "5,00,000.00", "", "10,32,500.00"), # ROUND_AMOUNT_OBSERVATION
      ("20/08/2025", "CASH DEP", "", "1,00,000.00", "11,32,500.00"),              # SEC_269ST_WARNING
      ("01/09/2025", "NACH-INSURANCE-LIC", "12,500.00", "", "11,20,000.00"),
      ("15/10/2025", "CASH WITHDRAWAL", "4,00,000.00", "", "7,20,000.00"),         # SFT cumulative cash withdrawal
      ("01/12/2025", "INTEREST CREDITED Q3", "", "38,000.00", "7,58,000.00"),
      ("15/01/2026", "IMPS-CONTRACTOR-PAY", "1,50,000.00", "", "6,08,000.00"),    # ROUND_AMOUNT_OBSERVATION
      ("01/03/2026", "CASH DEP FY END", "", "2,00,000.00", "8,08,000.00"),         # SEC_269ST_VIOLATION
  ]

  pdf.set_font("Helvetica", "", 8)
  for txn in transactions:
      for val, w in zip(txn, widths):
          pdf.cell(w, 7, val, border=1)
      pdf.ln()

  pdf.output("test_bank_statement.pdf")
  print("Created test_bank_statement.pdf")