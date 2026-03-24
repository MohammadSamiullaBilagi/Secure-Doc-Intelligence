# Blueprint Reference

## Blueprint JSON Format
```json
{
  "blueprint_id": "UNIQUE_ID",
  "name": "Display Name",
  "description": "What this blueprint checks",
  "checks": [
    {
      "check_id": "UNIQUE_CHECK_ID",
      "focus": "What to look for / extract from the document",
      "rule": "The enforcement criterion — what constitutes compliance or violation"
    }
  ]
}
```

Blueprint files go in `blueprints/` directory. Named `{something}_blueprint.json`.
The upload form sends `blueprint_file` as the filename string (e.g., `"gst_blueprint.json"`).
`services/blueprint_service.py` loads and validates them.
Users can also create custom blueprints stored in DB (`blueprints` table, `rules_json` column).

## Existing Blueprints

### `gst_blueprint.json` — GST_CA_AUDIT_2026_PRO
7 checks covering:
- GST_01: Invoice mandatory fields (Rule 46 CGST)
- GST_02: GSTIN validation (format check)
- GST_03: E-invoice compliance (IRN, QR code)
- GST_04: Blocked ITC under Section 17(5)
- GST_05: Rule 36(4) GSTR-2B reconciliation
- MSME_06: Section 43B(h) MSME payment terms (15/45 days)
- GST_07: Tax rate validation vs HSN/SAC

### `rbi_blueprint.json`
RBI compliance checks (contents not fully reviewed — use `Read` tool if needed)

## Missing Blueprints (P1 Priority — add these)

### `income_tax_blueprint.json` (suggested checks)
- IT_01: Section 40A(3) — cash payments >₹10,000 to single person in a day
- IT_02: Section 40(a)(ia) — TDS not deducted on contractor/professional fees
- IT_03: Section 43B — statutory payments (PF, ESI, tax) paid before due date
- IT_04: Section 36(1)(va) — employee PF/ESI deposited after due date
- IT_05: Section 14A — expenses relating to exempt income disallowance
- IT_06: Related party transactions disclosure (Section 40A(2))
- IT_07: Depreciation calculation (Section 32) — rate check, asset classification

### `tds_blueprint.json` (suggested checks)
- TDS_01: TDS on salary (Section 192) — deducted at correct rate
- TDS_02: TDS on rent (Section 194I) — 10% above ₹2.4L annual threshold
- TDS_03: TDS on professional/technical fees (Section 194J) — 10%
- TDS_04: TDS on contractor payments (Section 194C) — 1% individual, 2% others
- TDS_05: TDS deposited by 7th of following month
- TDS_06: Form 15G/15H validity where lower/nil deduction claimed
- TDS_07: TAN number present and valid

### `tax_audit_3cd_blueprint.json` (Form 3CD clause-wise)
- AUDIT_01: Clause 19 — depreciation admissibility
- AUDIT_02: Clause 21 — inadmissible expenses in P&L
- AUDIT_03: Clause 26 — employee contributions to PF/ESI (deposited timely)
- AUDIT_04: Clause 34 — TDS/TCS compliance summary
- AUDIT_05: Clause 44 — GST breakup of total expenditure

### `balance_sheet_blueprint.json` (red flag checks)
- BS_01: Unexplained cash balance above ₹2 lakh
- BS_02: Loans to directors — Section 185 compliance
- BS_03: Investment valuation — AS-13 lower of cost or market
- BS_04: Related party disclosures — AS-18
- BS_05: Contingent liabilities disclosed
- BS_06: Debtors >6 months — provision adequacy

## How Blueprints Connect to the Pipeline
1. User selects blueprint on upload form → `blueprint_file` form field = `"gst_blueprint.json"`
2. `WatcherService` passes to `ComplianceOrchestrator`
3. `blueprint_service.load_blueprint(blueprint_file)` reads JSON → returns `Blueprint` schema object
4. `Researcher` node calls `agent.extract_structured_fields(blueprint_dict, ...)` → extracts all check fields
5. `Auditor` node iterates each check → `agent.extract_for_audit(check.focus, check.rule, ...)` → LLM judges compliance
6. Results accumulate in `MultiAgentState.audit_results` as `AuditResult` objects

## AuditResult Schema
```python
class AuditResult:
    check_id: str
    focus: str
    rule: str
    compliance_status: str  # "COMPLIANT" | "PARTIAL" | "NON_COMPLIANT" | "INCONCLUSIVE"
    evidence: str           # direct quotes from document
    violation_details: str  # what specifically is wrong
    suggested_amendment: str  # what to do to fix it
```
