# Test Suite — Expected Audit Results
# Use this file to verify your system's accuracy against these 3 test documents.
# Each section shows: Check ID → Expected Status → Evidence → Expected Issue → Expected Fix

---

## PDF 1: test_gst_invoice.pdf
### Blueprint: GST_CA_AUDIT_2026_PRO
### Supplier: Pinnacle Hospitality Services Pvt Ltd | Invoice: PHS/2025-26/0847

---

### GST_01_INVOICE_MANDATORY_FIELDS → PARTIAL

**Evidence the system should extract:**
- supplier_name: Pinnacle Hospitality Services Pvt Ltd ✓
- supplier_gstin: 29AAECP4321R1ZK ✓
- invoice_number: PHS/2025-26/0847 ✓
- invoice_date: 12-Feb-2026 ✓
- recipient_gstin: 29AADCM5678Q1Z3 ✓
- taxable_value: 1,50,000.00 ✓
- place_of_supply: Karnataka (29) ✓
- tax_amount_cgst: 13,500.00 ✓
- tax_amount_sgst: 13,500.00 ✓
- hsn_sac_code: NOT PROVIDED / not found ✗
- signature: Not present (note at bottom says "not mandatory for e-invoices" — but IRN is invalid, so this excuse fails) ✗

**Expected Issue:**
Invoice is missing SAC codes for all 3 line items (shown as "NOT PROVIDED") and
has no valid physical or digital signature. Both are mandatory under Rule 46 of CGST Rules.

**Expected Fix:**
Supplier must add SAC codes for each service line:
- Club membership → SAC 999591
- Outdoor catering → SAC 996334
- Health consultation → SAC 999311
Also include authorised signatory signature or valid IRN (e-invoice).

---

### GST_02_GSTIN_VALIDATION → COMPLIANT

**Evidence:** supplier_gstin = 29AAECP4321R1ZK
- State code: 29 (Karnataka) ✓
- PAN portion: AAECP4321R ✓ (10 chars)
- Entity code: 1 ✓
- Z: Z ✓
- Checksum: K ✓

**Expected Issue:** None
**Expected Fix:** None

---

### GST_03_E_INVOICE_COMPLIANCE → NON_COMPLIANT

**Evidence the system should extract:**
- e_invoice_irn: "Present" (just the word Present — not an actual IRN)
- irn: NOT AVAILABLE (null/missing)
- irp_acknowledgement_number: NOT AVAILABLE (null/missing)
- acknowledgement_date: NOT AVAILABLE (null/missing)
- qr_code: NOT PRINTED (null/missing)

**Expected Issue:**
Invoice states "E-Invoice IRN: Present" but the actual 64-character IRN is "NOT AVAILABLE",
IRP acknowledgement number is missing, acknowledgement date is missing, and QR code is
not printed. This constitutes a complete e-invoicing breach. The invoice is treated as
invalid for ITC purposes by the recipient.

**Expected Fix:**
Supplier must generate a valid IRN through the IRP portal, obtain the IRP acknowledgement
number and date, and print the QR code on the invoice before re-issuing to the recipient.

---

### GST_04_BLOCKED_ITC_SECTION_17_5 → NON_COMPLIANT

**Evidence the system should extract:**
- Line 1: Corporate Club Membership → Section 17(5)(b)(i) — club membership blocked
- Line 2: Outdoor Catering Services → Section 17(5)(b)(ii) — outdoor catering blocked
- Line 3: Health & Wellness Consultation → Section 17(5)(b)(iii) — health services blocked
- itc_eligible: false for all 3 lines
- Total ITC blocked: Rs 27,000 (CGST 13,500 + SGST 13,500)

**Expected Issue:**
All three services on this invoice fall under Section 17(5) blocked ITC categories:
(1) Club membership is blocked under 17(5)(b)(i); (2) Outdoor catering blocked under
17(5)(b)(ii); (3) Health services blocked under 17(5)(b)(iii). Recipient (Meridian
Software Solutions) cannot claim any ITC from this invoice — total ITC of Rs 27,000
is ineligible.

**Expected Fix:**
Recipient must not claim ITC on this invoice. If services have a legitimate business
exception (e.g. catering mandatory for employees under a statutory obligation), obtain
a CA opinion before claiming. Otherwise reverse any ITC already claimed.

---

### GST_05_RULE_36_4_RECONCILIATION → NON_COMPLIANT

**Evidence:**
- gstr_2b_match: null / "This invoice has NOT been reflected in GSTR-2B"
- itc_eligible: false (both for blocked ITC and GSTR-2B mismatch)

**Expected Issue:**
Invoice explicitly states it has not been reflected in GSTR-2B. Even if ITC were otherwise
eligible, it cannot be claimed without GSTR-2B reflection per Rule 36(4). This is a
compounded risk — ITC is blocked on two independent grounds (Section 17(5) AND GSTR-2B).

**Expected Fix:**
Recipient should wait for GSTR-2B reflection before considering any ITC claim. Given the
Section 17(5) block, ITC remains ineligible regardless of GSTR-2B status.

---

### MSME_06_SECTION_43B_H → NON_COMPLIANT

**Evidence:**
- payment_terms: 50 days from invoice date
- maximum_allowed: 45 days
- days_excess: 5 days
- invoice_date: 12-Feb-2026
- due_date_shown: 03-Apr-2026 (which is 50 days)
- compliant_due_date_should_be: 29-Mar-2026 (45 days)

**Expected Issue:**
Payment terms of 50 days exceed the 45-day maximum under Section 43B(h) of the Income Tax
Act for MSME vendors. If Pinnacle Hospitality Services is registered as an MSME, any payment
made after 29-Mar-2026 will be disallowed as a deduction for Meridian Software Solutions in
FY 2025-26 and allowed only in the year of actual payment.

**Expected Fix:**
Revise payment terms to 45 days maximum (due date: 29-Mar-2026). Verify MSME registration
status of Pinnacle Hospitality Services on Udyam portal before payment.

---

### GST_07_TAX_RATE_VALIDATION → INCONCLUSIVE

**Evidence:** hsn_sac_code = NOT PROVIDED for all line items
**Expected Issue:** Cannot validate GST rate applicability without SAC codes.
Club membership, catering, and health services all have different applicable GST rates
(some at 18%, some at 5% for catering) — rate validation impossible without SAC codes.
**Expected Fix:** Obtain SAC codes from supplier. Club membership: 18% GST applicable.
Outdoor catering: 5% (without ITC) or 18% (with ITC). Health consultation: verify rate.

---

## PDF 2: test_tds_compliance.pdf
### Blueprint: TDS_TCS_CA_AUDIT_2026_PRO
### Company: Nexatech Innovations Pvt Ltd | TAN: BLRN12345E

---

### TDS_01_DEDUCTION_AT_CORRECT_RATE → PARTIAL

**Evidence the system should extract:**
- Cloudbase Tech LLP: TDS @2% under 194J (technical services) — QUERY flagged
- Mr. Ramesh Nair: PAN "NOT PROVIDED", TDS deducted @10% — should be @20% under 206AA
- All other vendors: rates appear correct

**Expected Issue:**
Two rate discrepancies identified:
(1) Cloudbase Tech LLP — classified as "technical services" at 2% but document notes
"management consulting elements present." If nature of service is professional/managerial,
rate should be 10% under 194J(a). Shortfall risk: Rs 28,000.
(2) Mr. Ramesh Nair — PAN not provided. Section 206AA mandates TDS at higher of: 20%,
applicable rate, or rate in force. TDS deducted @10% only. Shortfall: Rs 4,500.

**Expected Fix:**
(1) Obtain service agreement from Cloudbase Tech LLP and classify as pure technical (2%)
or professional (10%). Pay differential if 10% applies.
(2) Collect PAN from Mr. Ramesh Nair immediately. Deposit shortfall of Rs 4,500 with
interest @1% per month from date of deduction.

---

### TDS_02_TIMELY_DEPOSIT_CHALLAN → PARTIAL

**Evidence:**
- March 2026 rent TDS (Ms. Anjali Sharma): deposit date 30-Apr-2026
- Statutory deadline for March TDS: 30-Apr-2026
- All other months: deposited by 7th of following month ✓
- WazirX VDA transaction: TDS not deducted at all (Section 194S)

**Expected Issue:**
March 2026 rent TDS deposited on 30-Apr-2026 — exactly on deadline. Status borderline;
verify challan timestamp (if deposited after banking hours on 30th, it may be treated as
deposited on 1st May). All other months are compliant. However, VDA (Bitcoin) transaction
of Rs 2,50,000 had zero TDS — constitutes non-deposit of TDS that should have been deducted
under Section 194S.

**Expected Fix:**
Confirm challan timestamp for 30-Apr deposit. For future March TDS, target 25th April to
avoid last-minute risk. For VDA TDS default, deposit Rs 2,500 with interest immediately
and disclose in Form 26Q Q4.

---

### TDS_03_QUARTERLY_RETURN_FILING → PARTIAL

**Evidence:**
- Q1: Filed 31-Jul-2025 — on time ✓
- Q2: Filed 31-Oct-2025 — on time ✓
- Q3: Filed 14-Feb-2026 — 14 days late, penalty Rs 2,800 ✗
- Q4: PENDING ✓ (not yet due at report date)

**Expected Issue:**
Q3 TDS return (Form 26Q) filed 14 days late. Penalty under Section 234E: Rs 200/day x
14 days = Rs 2,800. If not already paid, this will appear as demand in TRACES. Additionally
the Section 194S VDA default must be included in Q4 return with corrected data.

**Expected Fix:**
Pay Section 234E penalty of Rs 2,800 for Q3 via TRACES. Include VDA TDS in Q4 return.
File Q4 by 31-May-2026.

---

### TDS_04_FORM_16_16A_ISSUANCE → PARTIAL

**Evidence:**
- Q1, Q2: Issued on time ✓
- Q3: Issued 28-Feb-2026, due 15-Feb-2026 — 13 days late ✗
- Q4: Pending ✓

**Expected Issue:**
Q3 Form 16A issued 13 days after due date. Penalty under Section 272A(2)(g): Rs 100/day
x 13 days = Rs 1,300 per deductee. With multiple deductees for Q3, total penalty could
be significant.

**Expected Fix:**
Pay applicable penalties. For Q4, issue Form 16A by 15-Jun-2026. Set internal calendar
reminder 10 days before due date.

---

### TDS_05_194A_BANK_INTEREST_THRESHOLD → COMPLIANT

**Evidence:**
- SBI FD interest: Rs 85,000 — exceeds Rs 50,000 threshold ✓
- TDS deducted @10% ✓
- Deposited 07-Jan-2026 ✓
- No Form 15G/15H filed by company (correctly not applicable for companies)

**Expected Issue:** None
**Expected Fix:** None

---

### TDS_06_SECTION_194S_VDA_CRYPTO → NON_COMPLIANT

**Evidence:**
- WazirX Crypto Exchange: Bitcoin sale Rs 2,50,000
- TDS deducted: NIL
- Section 194S applicable: YES (exceeds Rs 50,000 threshold)
- TDS required: Rs 2,500 @1%
- Deposit date: No challan

**Expected Issue:**
Bitcoin sale proceeds of Rs 2,50,000 through WazirX exchange. Section 194S requires buyer
to deduct TDS @1% on transfer of VDA where consideration exceeds Rs 50,000. TDS of Rs 2,500
was not deducted or deposited. This is a TDS default attracting interest @1.5%/month under
Section 201(1A) and potential penalty.

**Expected Fix:**
Deposit Rs 2,500 TDS with interest. Include in Q4 Form 26Q. Note: if transaction was
through exchange, the exchange (WazirX) may have responsibility — verify whether 194S(2)
exchange route applies which shifts responsibility to the exchange.

---

### TDS_07_LOWER_DEDUCTION_CERTIFICATE_VALIDITY → INCONCLUSIVE

**Evidence:** No lower deduction certificates (Form 13) mentioned in the document.
**Expected Issue:** None identified — no Form 13 certificates on record to validate.
**Expected Fix:** None required unless Form 13 certificates exist outside this document.

---

### TDS_08_PAN_VERIFICATION_HIGHER_RATE → NON_COMPLIANT

**Evidence:**
- Mr. Ramesh Nair: PAN = "NOT PROVIDED"
- TDS deducted: Rs 4,500 @10%
- Required under 206AA: 20% = Rs 9,000
- Shortfall: Rs 4,500

**Expected Issue:**
Mr. Ramesh Nair (freelance developer) did not provide PAN. Section 206AA mandates TDS at
higher of 20% or applicable rate. TDS deducted at 10% only. Shortfall of Rs 4,500
constitutes a TDS default. Nexatech is treated as an assessee in default for this amount.

**Expected Fix:**
Collect PAN from Mr. Ramesh Nair. Deposit shortfall Rs 4,500 with interest @1%/month
from September 2025 (date of deduction). Revise Form 26Q for Q2 with correct data.

---

### TDS_09_FORM_15G_15H_VALIDITY → NON_COMPLIANT

**Evidence:**
- M/s Orbit Traders: Form 15G with declared income Rs 2,80,000; actual estimated Rs 6,75,000
- Mr. Vinod Kumar: Form 15G not uploaded to TRACES within deadline

**Expected Issue:**
(1) M/s Orbit Traders submitted Form 15G declaring income below exemption limit, but actual
estimated income is Rs 6,75,000 — well above the basic exemption. Form 15G is invalid.
Nexatech should have deducted TDS and accepting an invalid 15G exposes them to penalty
under Section 277A.
(2) Mr. Vinod Kumar's Form 15G was not uploaded to TRACES portal by 7th of the following
quarter as required under Rule 31A. This is a compliance default.

**Expected Fix:**
(1) Deduct TDS retrospectively on all payments to M/s Orbit Traders. Report default to
TRACES. Seek legal advice on Section 277A exposure.
(2) Upload Mr. Vinod Kumar's Form 15G to TRACES immediately. Pay applicable late fee.

---

### TDS_10_TAN_REGISTRATION_AND_QUOTING → COMPLIANT

**Evidence:** TAN = BLRN12345E (present in document header)
- Format: 4 alpha + 5 numeric + 1 alpha ✓
- Quoted on quarterly returns: Q1, Q2 on time (confirmed by filing status) ✓

**Expected Issue:** None
**Expected Fix:** None

---

## PDF 3: test_income_tax_pl.pdf
### Blueprint: INCOME_TAX_CA_AUDIT_2026_PRO
### Entity: Harish Trading Co. | PAN: AABPH3456Q | FY 2025-26

---

### IT_01_SECTION_44AB_APPLICABILITY → COMPLIANT (with note)

**Evidence:**
- Business turnover (hardware + software + consultancy): ~Rs 2,15,65,000
- Exceeds Rs 1 crore threshold → Tax audit mandatory
- Digital transaction percentage: not calculable from document alone (flag for verification)

**Expected Issue:** None — tax audit is mandatory and document appears to be a tax audit extract.
**Note for system:** Flag that digital transaction percentage needs verification to confirm
whether Rs 10 crore threshold applies instead.

---

### IT_02_FORM_3CD_CLAUSE_19_DEDUCTIONS → PARTIAL

**Evidence:**
- Depreciation not detailed in this extract — block-wise schedule not shown
- Office equipment WDV loss mentioned (Rs 15,000)
- Professional fees, salary, and other revenue expenses visible

**Expected Issue:**
Depreciation schedule not included in this extract. System should flag that block-wise
depreciation computation under Income Tax Rules is required for Form 3CD Clause 19 and
request the depreciation schedule as a separate document.

---

### IT_03_SECTION_40A3_CASH_PAYMENTS → NON_COMPLIANT

**Evidence:**
- Transport & Freight: Rs 4,85,000 total — cash payments multiple
- Specific cash transactions: 14-Jun-25 Rs 18,000; 22-Aug-25 Rs 25,000;
  07-Nov-25 Rs 15,500; 19-Jan-26 Rs 12,000; 03-Mar-26 Rs 11,000
- Each payment exceeds Rs 10,000 to same payee(s) on single day
- Total disallowable cash: Rs 81,500
- Miscellaneous: Rs 68,000 cash — individual transaction amounts unknown (QUERY)

**Expected Issue:**
Cash payments to transporters on 5 separate occasions each exceed Rs 10,000 per day per
person — total Rs 81,500 disallowable under Section 40A(3). Additional Rs 68,000
miscellaneous cash expenses require voucher-level verification to determine if any
individual payment exceeded Rs 10,000.

**Expected Fix:**
Disallow Rs 81,500 in tax computation. For future payments, mandate NEFT/RTGS for any
single transport payment above Rs 10,000. Obtain and review miscellaneous expense vouchers.

---

### IT_04_SECTION_43B_STATUTORY_DUES → NON_COMPLIANT

**Evidence:**
- Employee PF (employer contribution): Rs 1,62,000 — payment details not shown
- Employee PF (employee share): Rs 81,000 — deposited 25-May-2026
- Statutory due date for PF employee share: 15-Apr-2026 (15th of following month)
- Delay: 40 days past due date

**Expected Issue:**
Employee PF contribution of Rs 81,000 (deducted from employees' salaries) deposited
25-May-2026, which is 40 days after the statutory due date of 15-Apr-2026. Under Section
36(1)(va) as confirmed by the Supreme Court in Checkmate Services Pvt Ltd v CIT (2022),
employee contributions deposited after the statutory due date are FULLY disallowed — even
if deposited before the ITR filing date. Disallowance: Rs 81,000.

Note: This is distinct from Section 43B (which applies to employer's own dues).
Section 36(1)(va) applies specifically to employee contributions and has no ITR-date grace.

**Expected Fix:**
Add back Rs 81,000 in tax computation for FY 2025-26. Amount will be deductible in
FY 2026-27 (year of deposit). Implement system to auto-deposit employee PF by 15th of
each month.

---

### IT_05_CAPITAL_GAINS_CLASSIFICATION → PARTIAL

**Evidence:**
- Reliance Industries: 13 months holding → LTCG ✓
- HDFC Mid-cap Fund: 19 months → LTCG ✓
- Gold ETF: 15 months → classified STCG (correct — gold ETF requires 24 months for LTCG)
- LTCG total: Rs 1,80,000; taxable after Rs 1.25L exemption: Rs 55,000 @12.5%
- STCG on Gold ETF: Rs 8,000 @20%

**Expected Issue:**
Classification appears broadly correct. However: Gold ETF at 15 months is correctly STCG
(not LTCG — non-equity asset, 24 months needed). Tax rate 20% is correct for STCG on
non-equity assets. Verify that LTCG exemption of Rs 1.25 lakh is applied against
equity+equity MF combined only (not Gold ETF).

---

### IT_06_CHAPTER_VIA_DEDUCTIONS → INCONCLUSIVE

**Evidence:** P&L extract does not contain Chapter VI-A deduction details.
**Expected Issue:** Deductions under 80C, 80D, 80G not visible in this document. Since this
is a proprietorship, personal deductions of proprietor must be verified separately.
**Expected Fix:** Request Schedule VI-A from ITR workings. Verify 80C (Rs 1.5L max), 80D,
and that no deductions claimed under new regime (Section 115BAC).

---

### IT_07_ADVANCE_TAX_COMPLIANCE → NON_COMPLIANT

**Evidence:**
- Tax liability estimated: Rs 7,00,000
- Q1 required: Rs 1,05,000 (15%), paid Rs 50,000 — shortfall Rs 55,000
- Q2 required: Rs 3,15,000 (45%), paid Rs 2,50,000 — shortfall Rs 65,000
- Q3 required: Rs 5,25,000 (75%), paid Rs 5,00,000 — shortfall Rs 25,000
- Q4 required: Rs 7,00,000 (100%), paid Rs 6,85,000 — shortfall Rs 15,000

**Expected Issue:**
Advance tax underpaid in all 4 instalments. Shortfalls attract:
- Section 234C interest: 1% per month on each instalment shortfall (simple interest)
  Q1: Rs 55,000 x 1% x 3 months = Rs 1,650
  Q2: Rs 65,000 x 1% x 3 months = Rs 1,950
  Q3: Rs 25,000 x 1% x 3 months = Rs 750
  Q4: Rs 15,000 x 1% x 1 month = Rs 150
  Total Section 234C: ~Rs 4,500
- Section 234B: If total advance tax (Rs 6,85,000) < 90% of assessed tax,
  additional monthly interest applies on shortfall from April 2026 to assessment.

**Expected Fix:**
Deposit balance tax Rs 15,000 immediately with Section 234B interest. CA to compute exact
234C interest and include in self-assessment tax challan.

---

### IT_08_RETURN_FILING_DUE_DATE → INCONCLUSIVE

**Evidence:** Document dated 15-Mar-2026; ITR not yet filed (FY still in progress).
**Expected Issue:** None currently — AY 2026-27 return due 31-Oct-2026 (tax audit case).
**Note:** System should flag to monitor filing. Document confirms turnover > Rs 1 crore,
so 31-Oct-2026 deadline applies (not 31-Jul-2026).

---

### IT_09_SECTION_40A_IA_TDS_DISALLOWANCE → NON_COMPLIANT

**Evidence:**
- Office Rent: Rs 6,60,000 (Rs 55,000/month x 12) paid to individual landlord
- TDS under 194I: NIL (not deducted)
- Threshold: Rs 2,40,000/year — threshold breached
- 30% disallowance: Rs 6,60,000 x 30% = Rs 1,98,000

**Expected Issue:**
Office rent of Rs 6,60,000 paid to individual landlord exceeds the Rs 2,40,000 annual
threshold for Section 194I TDS. TDS was not deducted throughout the year. Under Section
40(a)(ia), 30% of such payments (Rs 1,98,000) is disallowed as a business expense in
FY 2025-26. The disallowed amount will be allowed in the year TDS is deposited.

**Expected Fix:**
Deduct TDS on pending dues immediately. For past payments, deposit TDS with interest
@1%/month (for non-deduction period). Add back Rs 1,98,000 in tax computation.
Claim deduction in next year when TDS deposited.

---

### IT_10_SECTION_36_1_VA_EMPLOYEE_PF_ESI → NON_COMPLIANT

*(Same as IT_04 above — both checks should catch this. System gets credit for finding it
under either or both check IDs.)*

**Evidence:** Employee PF Rs 81,000 deposited 25-May-2026 vs due date 15-Apr-2026.
**Expected Issue:** Full disallowance of Rs 81,000 under Section 36(1)(va).
**Expected Fix:** Add back Rs 81,000. Pay on time in future years.

---

### IT_11_SECTION_14A_EXEMPT_INCOME_DISALLOWANCE → NON_COMPLIANT

**Evidence:**
- Dividend income: Rs 1,25,000 (exempt u/s 10(35))
- Investment in equity mutual funds: Rs 15,00,000
- Rule 8D computation: 1% of avg investment = Rs 15,000 minimum
- Direct expenditure attributed to exempt income: to be computed separately

**Expected Issue:**
Dividend income of Rs 1,25,000 is exempt. Investments generating this income (Rs 15,00,000
in equity mutual funds) must attract Section 14A disallowance under Rule 8D:
- 1% of average value of investments: Rs 15,000
- Plus direct expenditure (brokerage, advisory): to be identified
Total estimated disallowance: Rs 15,000+

**Expected Fix:**
Compute Rule 8D disallowance in tax workings. Identify direct expenditure (brokerage,
Demat charges) attributable to equity mutual fund portfolio. Include total in Form 3CD
Clause 14 disclosure.

---

### IT_12_RELATED_PARTY_TRANSACTIONS_DISCLOSURE → NON_COMPLIANT

**Evidence:**
- Harish Enterprises: management fee Rs 4,50,000
- Relationship: proprietor's brother's firm — qualifies as "relative" under Section 40A(2)(b)
- Market rate for comparable services: Rs 2,80,000 (per document)
- Excess payment: Rs 1,70,000

**Expected Issue:**
Payment of Rs 4,50,000 to Harish Enterprises (related party — proprietor's brother)
exceeds market rate of Rs 2,80,000 by Rs 1,70,000. Under Section 40A(2), excess payment
of Rs 1,70,000 is disallowed. Transaction must be disclosed in Form 3CD Clause 23.
If arm's length documentation is absent, AO may make a higher disallowance.

**Expected Fix:**
Disallow Rs 1,70,000 in tax computation. Obtain comparable market quotes for management
services and document them. Disclose in Form 3CD Clause 23 with relationship details.

---

## Summary: Expected Accuracy Benchmarks

| PDF | Blueprint | Total Checks | Expected NON_COMPLIANT | Expected PARTIAL | Expected COMPLIANT | Expected INCONCLUSIVE |
|---|---|---|---|---|---|---|
| test_gst_invoice.pdf | GST_CA_AUDIT_2026_PRO | 7 | 4 | 1 | 1 | 1 |
| test_tds_compliance.pdf | TDS_TCS_CA_AUDIT_2026_PRO | 10 | 4 | 2 | 3 | 1 |
| test_income_tax_pl.pdf | INCOME_TAX_CA_AUDIT_2026_PRO | 12 | 6 | 2 | 1 | 3 |

**Scoring guide:**
- Status match correct → 1 point per check
- Evidence extracted correctly (key fields present) → 1 point per check
- Issue description covers the core problem → 1 point per check
- Score >= 80% → System ready for production
- Score 60–79% → Prompt engineering needed
- Score < 60% → Blueprint rules need to be rewritten with more specificity
