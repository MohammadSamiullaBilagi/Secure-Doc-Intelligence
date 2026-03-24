"""Create realistic Indian tax notice PDFs for testing the Notice Reply Assistant."""

from fpdf import FPDF
from datetime import date


def _s(text: str) -> str:
    """Sanitize text for fpdf2 (replace unsupported chars)."""
    return (
        text.replace("\u2018", "'").replace("\u2019", "'")
        .replace("\u201c", '"').replace("\u201d", '"')
        .replace("\u2013", "-").replace("\u2014", "-")
        .replace("\u20b9", "Rs.").replace("\u2026", "...")
    )


# ============================================================================
# 1. Section 143(1) — Income Tax Intimation
# ============================================================================

def create_143_1_notice():
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_left_margin(20)
    pdf.set_right_margin(20)
    pdf.add_page()
    w = pdf.w - pdf.l_margin - pdf.r_margin

    # Header
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "INCOME TAX DEPARTMENT", ln=True, align="C")
    pdf.cell(0, 8, "GOVERNMENT OF INDIA", ln=True, align="C")
    pdf.ln(3)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "INTIMATION UNDER SECTION 143(1)", ln=True, align="C")
    pdf.cell(0, 8, "OF THE INCOME TAX ACT, 1961", ln=True, align="C")
    pdf.ln(5)

    pdf.set_font("Helvetica", "", 9)
    pdf.cell(w / 2, 6, _s("CPC Reference No: CPC/2526/143(1)/2890714"))
    pdf.cell(w / 2, 6, "Date of Issue: 15/01/2026", ln=True, align="R")
    pdf.ln(3)

    # Assessee details
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 7, "DETAILS OF ASSESSEE", ln=True)
    pdf.set_font("Helvetica", "", 9)

    details = [
        ("PAN", "ABCPK1234F"),
        ("Name", "M/s KRISHNA TRADING COMPANY"),
        ("Address", "Shop No. 14, Mahatma Gandhi Road, Andheri East, Mumbai - 400069"),
        ("Assessment Year", "2025-26"),
        ("Filing Date", "28/07/2025"),
        ("ITR Form", "ITR-3"),
        ("Acknowledgement No.", "CPC/ITR3/2025/1082637491"),
        ("Ward / Circle", "Ward 14(3)(2), Mumbai"),
    ]
    for label, val in details:
        pdf.cell(50, 6, _s(f"{label}:"))
        pdf.cell(0, 6, _s(val), ln=True)
    pdf.ln(5)

    # Computation
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 7, "COMPUTATION OF TOTAL INCOME AND TAX LIABILITY", ln=True)
    pdf.ln(2)

    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(220, 220, 220)
    pdf.cell(90, 6, "Particulars", border=1, fill=True)
    pdf.cell(35, 6, "As per Return", border=1, fill=True, align="C")
    pdf.cell(35, 6, "As per CPC", border=1, fill=True, align="C")
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    rows = [
        ("Income from Business / Profession", "18,45,200", "18,45,200"),
        ("Income from Other Sources (Interest)", "1,23,450", "1,82,670"),
        ("Gross Total Income", "19,68,650", "20,27,870"),
        ("Deduction u/s 80C (LIC, PPF, ELSS)", "1,50,000", "1,50,000"),
        ("Deduction u/s 80D (Mediclaim)", "25,000", "25,000"),
        ("Deduction u/s 80TTA (Savings Interest)", "10,000", "10,000"),
        ("Total Deductions", "1,85,000", "1,85,000"),
        ("Total Taxable Income", "17,83,650", "18,42,870"),
        ("Tax on Total Income", "3,09,095", "3,26,861"),
        ("Health & Education Cess @ 4%", "12,364", "13,074"),
        ("Total Tax & Cess", "3,21,459", "3,39,935"),
        ("Less: TDS as per Form 26AS", "2,85,000", "2,85,000"),
        ("Less: Advance Tax Paid", "25,000", "25,000"),
        ("Less: Self-Assessment Tax u/s 140A", "11,459", "11,459"),
        ("Net Tax Payable / (Refund)", "0", "18,476"),
        ("Interest u/s 234A", "0", "0"),
        ("Interest u/s 234B", "0", "554"),
        ("Interest u/s 234C", "0", "1,245"),
        ("TOTAL DEMAND PAYABLE", "0", "20,275"),
    ]
    for label, ret_val, cpc_val in rows:
        pdf.cell(90, 5, _s(label), border=1)
        pdf.cell(35, 5, _s(ret_val), border=1, align="R")
        pdf.cell(35, 5, _s(cpc_val), border=1, align="R")
        pdf.ln()

    pdf.ln(5)

    # Explanation
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 7, "EXPLANATION OF ADJUSTMENTS", ln=True)
    pdf.set_font("Helvetica", "", 9)

    adjustments = [
        "1. Mismatch in Income from Other Sources: Interest income of Rs.59,220 credited in savings "
        "account (SBI A/c No. 38291047562) was reported as Rs.1,23,450 in the return but Rs.1,82,670 "
        "was reflected in Form 26AS / AIS. The difference of Rs.59,220 has been added to your total income.",

        "2. Interest u/s 234B: Since advance tax paid (Rs.25,000) was less than 90% of assessed tax "
        "(Rs.3,39,935 x 90% = Rs.3,05,942), interest u/s 234B has been computed at 1% per month for "
        "3 months on the shortfall of Rs.18,476. Interest = Rs.554.",

        "3. Interest u/s 234C: Advance tax instalments were not paid as per the schedule prescribed "
        "u/s 211. Interest has been computed at 1% per month on the shortfall for each quarter. "
        "Total 234C interest = Rs.1,245.",
    ]
    for adj in adjustments:
        pdf.multi_cell(w, 5, _s(adj))
        pdf.ln(2)

    pdf.ln(3)

    # Response deadline
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(200, 0, 0)
    pdf.cell(0, 7, "IMPORTANT: RESPONSE DEADLINE", ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(w, 5, _s(
        "If you disagree with the above adjustments, you may file a rectification request u/s 154 "
        "within 30 days of receipt of this intimation, i.e., by 14/02/2026. If no response is "
        "received, the demand of Rs.20,275 shall be treated as confirmed and recovery proceedings "
        "may be initiated u/s 220(1) and 221 of the Income Tax Act, 1961."
    ))
    pdf.ln(3)

    pdf.multi_cell(w, 5, _s(
        "Payment of demand may be made online through the e-filing portal (https://www.incometax.gov.in) "
        "under 'e-Pay Tax' using Challan 280 (Tax on Regular Assessment - Code 400)."
    ))
    pdf.ln(5)

    # Footer
    pdf.set_font("Helvetica", "", 8)
    pdf.cell(0, 5, _s("This is a computer-generated intimation and does not require a signature."), ln=True, align="C")
    pdf.cell(0, 5, _s("Centralized Processing Centre, Income Tax Department, Bengaluru - 560100"), ln=True, align="C")
    pdf.cell(0, 5, _s("For grievances: cpcgrievance@incometax.gov.in | Toll-free: 1800-103-0025"), ln=True, align="C")

    pdf.output("test_notice_143_1.pdf")
    print("Created: test_notice_143_1.pdf (Section 143(1) Income Tax Intimation)")


# ============================================================================
# 2. DRC-01 — GST Show Cause Notice / Demand
# ============================================================================

def create_drc01_notice():
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_left_margin(20)
    pdf.set_right_margin(20)
    pdf.add_page()
    w = pdf.w - pdf.l_margin - pdf.r_margin

    # Header
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "GOVERNMENT OF MAHARASHTRA", ln=True, align="C")
    pdf.cell(0, 8, "OFFICE OF THE ASSISTANT COMMISSIONER", ln=True, align="C")
    pdf.cell(0, 8, "CENTRAL GOODS AND SERVICES TAX", ln=True, align="C")
    pdf.cell(0, 8, "DIVISION - IV, MUMBAI CENTRAL", ln=True, align="C")
    pdf.ln(3)

    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(180, 0, 0)
    pdf.cell(0, 10, "FORM GST DRC-01", ln=True, align="C")
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 7, "[See Rule 142(1)(a)]", ln=True, align="C")
    pdf.cell(0, 8, "SHOW CAUSE NOTICE FOR DEMAND OF TAX", ln=True, align="C")
    pdf.cell(0, 7, "Under Section 73 of the CGST Act, 2017", ln=True, align="C")
    pdf.ln(5)

    pdf.set_font("Helvetica", "", 9)
    pdf.cell(w / 2, 6, _s("SCN Reference No: CGST/MUM-IV/SCN/2025-26/1847"))
    pdf.cell(w / 2, 6, "Date: 02/02/2026", ln=True, align="R")
    pdf.cell(w / 2, 6, _s("DIN: 202526CGST001847MUM"))
    pdf.cell(w / 2, 6, _s("Tax Period: July 2025 to December 2025"), ln=True, align="R")
    pdf.ln(3)

    # To
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "To,", ln=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, _s("M/s KRISHNA TRADING COMPANY"), ln=True)
    pdf.cell(0, 5, _s("GSTIN: 27ABCPK1234F1ZV"), ln=True)
    pdf.cell(0, 5, _s("Shop No. 14, Mahatma Gandhi Road, Andheri East, Mumbai - 400069"), ln=True)
    pdf.ln(3)

    # Subject
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, _s(
        "Subject: Show Cause Notice for demand of tax not paid / short paid / erroneously "
        "refunded / wrongly availed or utilized Input Tax Credit for the period July 2025 "
        "to December 2025."
    ), ln=True)
    pdf.ln(3)

    # Body
    pdf.set_font("Helvetica", "", 9)
    body_paras = [
        "Sir/Madam,",

        "Whereas upon examination of the returns filed by you (GSTR-1, GSTR-3B) and the details "
        "available in GSTR-2A/2B for the tax period July 2025 to December 2025, it appears that "
        "there are discrepancies in the Input Tax Credit (ITC) availed by you, as detailed below:",

        "1. ITC CLAIMED WITHOUT VALID TAX INVOICES (Section 16(2)(a) read with Rule 36(4)):",

        "   During the period under review, you have availed ITC of Rs.4,85,200 (IGST: Rs.2,15,000, "
        "CGST: Rs.1,35,100, SGST: Rs.1,35,100) on purchases from the following suppliers whose "
        "invoices do not appear in your GSTR-2B:",

        "   a) M/s Shree Ganesh Enterprises (GSTIN: 27AADCS5678K1ZP) - Rs.2,10,000 "
        "(Invoice Nos: SGE/2025/0714, SGE/2025/0892, SGE/2025/1023)",

        "   b) M/s National Traders (GSTIN: 27AANPT9876L1ZQ) - Rs.1,45,200 "
        "(Invoice Nos: NT/25-26/445, NT/25-26/512, NT/25-26/601, NT/25-26/645)",

        "   c) M/s Kumar Steel Industries (GSTIN: 27AABCK4567M1ZR) - Rs.1,30,000 "
        "(Invoice Nos: KSI/2025/2847, KSI/2025/3012)",

        "2. ITC AVAILED ON BLOCKED CREDITS (Section 17(5)):",

        "   You have availed ITC of Rs.68,400 on the following items which are blocked credits "
        "under Section 17(5) of the CGST Act:",

        "   a) Motor vehicle insurance premium (Bajaj Allianz Policy No. OG-25-1234-5678) - Rs.42,300",
        "   b) Food and beverages for staff welfare (various invoices) - Rs.26,100",

        "3. TOTAL DEMAND COMPUTATION:",
    ]
    for para in body_paras:
        pdf.multi_cell(w, 5, _s(para))
        pdf.ln(1)

    # Demand table
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(220, 220, 220)
    pdf.cell(60, 6, "Particulars", border=1, fill=True)
    pdf.cell(25, 6, "IGST", border=1, fill=True, align="C")
    pdf.cell(25, 6, "CGST", border=1, fill=True, align="C")
    pdf.cell(25, 6, "SGST", border=1, fill=True, align="C")
    pdf.cell(25, 6, "Total", border=1, fill=True, align="C")
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    table_rows = [
        ("ITC without invoices (Sec 16)", "2,15,000", "1,35,100", "1,35,100", "4,85,200"),
        ("Blocked credits (Sec 17(5))", "0", "34,200", "34,200", "68,400"),
        ("Total Tax Demand", "2,15,000", "1,69,300", "1,69,300", "5,53,600"),
        ("Interest u/s 50 (@ 18% p.a.)", "19,350", "15,237", "15,237", "49,824"),
        ("Penalty u/s 73(9) (10%)", "21,500", "16,930", "16,930", "55,360"),
        ("TOTAL AMOUNT PAYABLE", "2,55,850", "2,01,467", "2,01,467", "6,58,784"),
    ]
    for label, igst, cgst, sgst, total in table_rows:
        pdf.cell(60, 5, _s(label), border=1)
        pdf.cell(25, 5, _s(igst), border=1, align="R")
        pdf.cell(25, 5, _s(cgst), border=1, align="R")
        pdf.cell(25, 5, _s(sgst), border=1, align="R")
        pdf.cell(25, 5, _s(total), border=1, align="R")
        pdf.ln()

    pdf.ln(5)
    pdf.set_font("Helvetica", "", 9)

    closing = [
        "You are hereby directed to show cause as to why the amount of Rs.6,58,784 (Rupees Six Lakh "
        "Fifty-Eight Thousand Seven Hundred Eighty-Four Only) as mentioned above, including tax, "
        "interest, and penalty, should not be demanded and recovered from you.",

        "You are advised to submit your reply along with supporting documents within 30 days from "
        "the date of receipt of this notice, i.e., by 04/03/2026, either personally or through "
        "authorized representative at the above-mentioned office or electronically through the GST "
        "Portal (www.gst.gov.in) under 'View Additional Notices and Orders'.",

        "If you wish to make payment of the tax demanded along with applicable interest, you may do "
        "so before the issuance of the order, and proceedings shall be deemed to be concluded in "
        "respect of the said tax amount as per Section 73(5) / 73(6) of the CGST Act, 2017.",

        "In case no reply is received within the stipulated time, the case will be decided ex-parte "
        "on the basis of available records and an order under Section 73(9) shall be passed without "
        "further reference to you.",

        "A personal hearing has been scheduled on 25/02/2026 at 11:00 AM at the office of the "
        "undersigned. You may attend in person or through an authorized representative.",
    ]
    for para in closing:
        pdf.multi_cell(w, 5, _s(para))
        pdf.ln(2)

    pdf.ln(3)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, _s("Sd/-"), ln=True, align="R")
    pdf.cell(0, 6, _s("(Amit R. Deshmukh)"), ln=True, align="R")
    pdf.cell(0, 6, _s("Assistant Commissioner, CGST"), ln=True, align="R")
    pdf.cell(0, 6, _s("Division IV, Mumbai Central"), ln=True, align="R")
    pdf.cell(0, 6, _s("Email: ac-div4-mumbai@gst.gov.in"), ln=True, align="R")

    pdf.output("test_notice_drc01.pdf")
    print("Created: test_notice_drc01.pdf (GST DRC-01 Show Cause Notice)")


# ============================================================================
# 3. Section 148 — Income Tax Reopening Notice
# ============================================================================

def create_148_notice():
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_left_margin(20)
    pdf.set_right_margin(20)
    pdf.add_page()
    w = pdf.w - pdf.l_margin - pdf.r_margin

    # Header
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "INCOME TAX DEPARTMENT", ln=True, align="C")
    pdf.cell(0, 8, "GOVERNMENT OF INDIA", ln=True, align="C")
    pdf.ln(3)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "NOTICE UNDER SECTION 148 OF THE INCOME TAX ACT, 1961", ln=True, align="C")
    pdf.cell(0, 7, "(As amended by Finance Act, 2021)", ln=True, align="C")
    pdf.ln(5)

    pdf.set_font("Helvetica", "", 9)
    pdf.cell(w / 2, 6, _s("Notice No: ITO/W-14(3)(2)/MUM/148/2025-26/3847"))
    pdf.cell(w / 2, 6, "Date: 28/12/2025", ln=True, align="R")
    pdf.cell(w / 2, 6, _s("DIN: 202526148003847MUM"))
    pdf.cell(w / 2, 6, "", ln=True)
    pdf.ln(3)

    # To
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, "To,", ln=True)
    pdf.cell(0, 5, _s("Shri Rajesh Kumar Patel"), ln=True)
    pdf.cell(0, 5, _s("PAN: ABCPK1234F"), ln=True)
    pdf.cell(0, 5, _s("Proprietor, M/s Krishna Trading Company"), ln=True)
    pdf.cell(0, 5, _s("Shop No. 14, Mahatma Gandhi Road, Andheri East, Mumbai - 400069"), ln=True)
    pdf.ln(3)

    # Subject line
    pdf.set_font("Helvetica", "B", 9)
    pdf.multi_cell(w, 5, _s(
        "Subject: Notice u/s 148 of the Income Tax Act, 1961 for Assessment Year 2023-24 "
        "- Reopening of Assessment"
    ))
    pdf.ln(3)

    pdf.set_font("Helvetica", "", 9)
    paragraphs = [
        "Sir,",

        "Whereas I have information which suggests that income chargeable to tax for the "
        "Assessment Year 2023-24 (Financial Year 2022-23) has escaped assessment within the "
        "meaning of Section 147 of the Income Tax Act, 1961, the following specific information "
        "has come to the notice of the Department:",

        "1. HIGH VALUE CASH DEPOSITS NOT EXPLAINED IN RETURN:",

        "   As per the Statement of Financial Transactions (SFT) / Annual Information Statement "
        "(AIS) available with the Department, the following high-value cash deposits were made "
        "in your bank accounts during FY 2022-23:",

        "   a) HDFC Bank A/c No. 50100287456321 (Andheri Branch):",
        "      - Cash deposit on 15/06/2022: Rs.8,50,000",
        "      - Cash deposit on 22/08/2022: Rs.6,25,000",
        "      - Cash deposit on 10/11/2022: Rs.9,75,000",
        "      - Cash deposit on 28/01/2023: Rs.7,00,000",
        "      Total: Rs.31,50,000",

        "   b) State Bank of India A/c No. 38291047562 (MIDC Branch):",
        "      - Cash deposit on 05/07/2022: Rs.4,80,000",
        "      - Cash deposit on 19/09/2022: Rs.5,50,000",
        "      - Cash deposit on 03/12/2022: Rs.6,00,000",
        "      Total: Rs.16,30,000",

        "   Aggregate cash deposits: Rs.47,80,000",

        "   However, in the ITR filed for AY 2023-24, your total gross receipts from business "
        "were declared as Rs.14,25,600 and total income as Rs.6,82,400. The cash deposits of "
        "Rs.47,80,000 are significantly higher than the declared turnover and remain unexplained.",

        "2. MISMATCH IN SECURITIES TRANSACTION TAX (STT) DATA:",

        "   As per the data received from stock exchanges, sale proceeds of Rs.12,45,000 from "
        "equity shares/mutual funds were recorded during FY 2022-23. However, no capital gains "
        "or losses have been reported in the ITR for AY 2023-24.",

        "3. PROPERTY TRANSACTION NOT REPORTED:",

        "   As per the Sub-Registrar records (SRO Andheri-IV), a property transaction "
        "(Document No. AND-4/2022/7845) dated 14/10/2022 involving sale consideration of "
        "Rs.62,00,000 for Flat No. 302, Sai Krupa CHS, Jogeshwari (E), Mumbai was registered "
        "in your name. Capital gains on this transaction have not been reported in the return.",

        "In view of the above information, I have reason to believe that income chargeable to "
        "tax amounting to Rs.50,00,000 or more has escaped assessment for AY 2023-24.",
    ]
    for para in paragraphs:
        pdf.multi_cell(w, 5, _s(para))
        pdf.ln(1)

    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 7, "DIRECTIONS:", ln=True)
    pdf.set_font("Helvetica", "", 9)

    directions = [
        "You are hereby required to furnish a return of your income for the Assessment Year "
        "2023-24, in the prescribed form, within 30 days from the date of service of this "
        "notice, i.e., by 27/01/2026.",

        "The return must be filed electronically on the e-filing portal and should include "
        "complete details of all income, including:",
        "   - Full details of all cash deposits with sources",
        "   - Capital gains from sale of shares/mutual funds",
        "   - Capital gains from sale of immovable property",
        "   - Any other income not previously disclosed",

        "You are also required to produce the following documents/evidence:",
        "   a) Bank statements for all bank accounts for FY 2022-23",
        "   b) Demat account statements and contract notes for equity transactions",
        "   c) Sale deed and computation of capital gains for property transaction",
        "   d) Source of cash deposits with supporting evidence (sale receipts, loan documents, etc.)",
        "   e) Books of account maintained for business",

        "Failure to comply with this notice may result in assessment being made to the best of "
        "judgement u/s 144 of the Act, and penalty proceedings u/s 271(1)(c) / 270A may be "
        "initiated for concealment of income / furnishing of inaccurate particulars.",

        "A personal hearing is scheduled for 20/01/2026 at 3:00 PM at the office of the "
        "undersigned. You may appear in person or through an authorized representative.",
    ]
    for para in directions:
        pdf.multi_cell(w, 5, _s(para))
        pdf.ln(1)

    pdf.ln(5)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 6, _s("Yours faithfully,"), ln=True, align="R")
    pdf.ln(3)
    pdf.cell(0, 6, _s("Sd/-"), ln=True, align="R")
    pdf.cell(0, 6, _s("(Priya S. Mehta, IRS)"), ln=True, align="R")
    pdf.cell(0, 6, _s("Income Tax Officer"), ln=True, align="R")
    pdf.cell(0, 6, _s("Ward 14(3)(2), Mumbai"), ln=True, align="R")
    pdf.cell(0, 6, _s("Room No. 412, Aayakar Bhavan, M.K. Road, Mumbai - 400020"), ln=True, align="R")
    pdf.cell(0, 6, _s("Email: ito-w14-3-2-mumbai@incometax.gov.in"), ln=True, align="R")

    pdf.output("test_notice_148.pdf")
    print("Created: test_notice_148.pdf (Section 148 Reopening Notice)")


# ============================================================================
# 4. Supporting Document — Bank Statement Extract (for 148 notice)
# ============================================================================

def create_supporting_bank_statement():
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.set_left_margin(15)
    pdf.set_right_margin(15)
    pdf.add_page()
    w = pdf.w - pdf.l_margin - pdf.r_margin

    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, "HDFC BANK LIMITED", ln=True, align="C")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 7, "Andheri East Branch, Mumbai - 400069", ln=True, align="C")
    pdf.ln(3)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, "STATEMENT OF ACCOUNT", ln=True, align="C")
    pdf.ln(3)

    pdf.set_font("Helvetica", "", 9)
    info = [
        ("Account Holder", "M/s KRISHNA TRADING COMPANY (Prop: Rajesh Kumar Patel)"),
        ("Account No.", "50100287456321"),
        ("Account Type", "Current Account"),
        ("Branch", "Andheri East, Mumbai"),
        ("IFSC", "HDFC0001234"),
        ("Period", "01/04/2022 to 31/03/2023"),
    ]
    for label, val in info:
        pdf.cell(40, 5, _s(f"{label}:"))
        pdf.cell(0, 5, _s(val), ln=True)
    pdf.ln(5)

    # Transaction table
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_fill_color(230, 230, 230)
    cols = [18, 60, 22, 22, 25]
    headers = ["Date", "Description", "Debit", "Credit", "Balance"]
    for i, h in enumerate(headers):
        pdf.cell(cols[i], 6, h, border=1, fill=True, align="C")
    pdf.ln()

    pdf.set_font("Helvetica", "", 7)
    transactions = [
        ("01/04/22", "Opening Balance", "", "", "3,45,200"),
        ("05/04/22", "NEFT-CR: XYZ Enterprises/INV-2204", "", "2,85,000", "6,30,200"),
        ("12/04/22", "RTGS-DR: Supplier payment - National Traders", "1,45,000", "", "4,85,200"),
        ("15/06/22", "CASH DEPOSIT", "", "8,50,000", "13,35,200"),
        ("20/06/22", "NEFT-DR: Rent payment June 2022", "45,000", "", "12,90,200"),
        ("05/07/22", "NEFT-CR: M/s Patel Brothers/PO-7845", "", "3,20,000", "16,10,200"),
        ("18/07/22", "UPI-DR: Electricity bill / MSEDCL", "12,450", "", "15,97,750"),
        ("22/08/22", "CASH DEPOSIT", "", "6,25,000", "22,22,750"),
        ("02/09/22", "RTGS-DR: Goods purchase - Kumar Steel", "4,50,000", "", "17,72,750"),
        ("19/09/22", "NEFT-CR: Sale proceeds / Mehta & Co", "", "1,85,000", "19,57,750"),
        ("14/10/22", "RTGS-CR: Property sale / SRO AND-4/7845", "", "62,00,000", "81,57,750"),
        ("20/10/22", "RTGS-DR: Home loan prepayment / HDFC Ltd", "35,00,000", "", "46,57,750"),
        ("10/11/22", "CASH DEPOSIT", "", "9,75,000", "56,32,750"),
        ("15/11/22", "NEFT-DR: Stock purchase - Zerodha", "8,00,000", "", "48,32,750"),
        ("05/12/22", "NEFT-CR: Brokerage receipt", "", "42,000", "48,74,750"),
        ("20/12/22", "RTGS-DR: Advance tax Q3 / Challan 280", "25,000", "", "48,49,750"),
        ("28/01/23", "CASH DEPOSIT", "", "7,00,000", "55,49,750"),
        ("05/02/23", "NEFT-CR: Customer payment / ABC Corp", "", "1,90,000", "57,39,750"),
        ("15/03/23", "RTGS-DR: Advance tax Q4 / Challan 280", "50,000", "", "56,89,750"),
        ("25/03/23", "NEFT-DR: Staff salary March 2023", "1,20,000", "", "55,69,750"),
        ("31/03/23", "Interest credited Q4", "", "18,420", "55,88,170"),
        ("31/03/23", "Closing Balance", "", "", "55,88,170"),
    ]
    for dt, desc, dr, cr, bal in transactions:
        pdf.cell(cols[0], 4.5, dt, border=1)
        pdf.cell(cols[1], 4.5, _s(desc[:40]), border=1)
        pdf.cell(cols[2], 4.5, _s(dr), border=1, align="R")
        pdf.cell(cols[3], 4.5, _s(cr), border=1, align="R")
        pdf.cell(cols[4], 4.5, _s(bal), border=1, align="R")
        pdf.ln()

    pdf.ln(5)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 6, "Summary:", ln=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, _s("Total Cash Deposits during FY 2022-23: Rs.31,50,000"), ln=True)
    pdf.cell(0, 5, _s("Total Credits (all modes): Rs.1,04,90,420"), ln=True)
    pdf.cell(0, 5, _s("Total Debits (all modes): Rs.52,47,450"), ln=True)
    pdf.ln(3)

    pdf.set_font("Helvetica", "I", 8)
    pdf.cell(0, 5, _s("This statement is generated as per customer's request. For official use."), ln=True, align="C")
    pdf.cell(0, 5, _s("HDFC Bank Ltd., Regd. Office: HDFC Bank House, Senapati Bapat Marg, Mumbai"), ln=True, align="C")

    pdf.output("test_notice_148_supporting_bank_stmt.pdf")
    print("Created: test_notice_148_supporting_bank_stmt.pdf (Supporting bank statement for 148 notice)")


if __name__ == "__main__":
    create_143_1_notice()
    create_drc01_notice()
    create_148_notice()
    create_supporting_bank_statement()
    print("\nAll 4 test notice PDFs created successfully!")
    print("\nTest scenarios:")
    print("  1. test_notice_143_1.pdf          -> notice_type: 143_1")
    print("  2. test_notice_drc01.pdf          -> notice_type: drc_01")
    print("  3. test_notice_148.pdf            -> notice_type: 148")
    print("     + test_notice_148_supporting_bank_stmt.pdf (as supporting_files)")
