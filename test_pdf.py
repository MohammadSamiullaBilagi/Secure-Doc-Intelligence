from api.routes.reports import _generate_audit_pdf

def test_pdf():
    # Test with dict-based audit results (simulating checkpointer state)
    audit_state = {
        "remediation_draft": {"requires_action": True, "email_subject": "Correction Required", "email_body": "Please fix the violations."},
        "audit_results": [
            {
                "compliance_status": "COMPLIANT",
                "check_id": "GST_01",
                "focus": "Invoice mandatory fields",
                "violation_details": "",
                "evidence": "supplier_name = Acme Corp, gstin = 29AAECM1234Q1Z5",
                "suggested_amendment": ""
            },
            {
                "compliance_status": "NON_COMPLIANT",
                "check_id": "GST_03",
                "focus": "E-invoicing compliance",
                "violation_details": "IRN and QR code are missing",
                "evidence": "irn = null, qr_code = null",
                "suggested_amendment": "Add valid IRN and QR code to invoice"
            },
            {
                "compliance_status": "PARTIAL",
                "check_id": "GST_05",
                "focus": "ITC eligibility",
                "violation_details": "GSTR-2B reflection not available",
                "evidence": "gstr_2b_reflection = null",
                "suggested_amendment": "Verify ITC claim against GSTR-2B"
            },
        ]
    }
    
    # Test with Pydantic AuditResult objects
    from schemas.blueprint_schema import AuditResult
    pydantic_state = {
        "remediation_draft": {"requires_action": False},
        "audit_results": [
            AuditResult(
                check_id="GST_01", focus="Invoice fields", rule="Must contain supplier",
                compliance_status="COMPLIANT", evidence="supplier_name = Acme Corp",
                violation_details="None", suggested_amendment="None"
            ),
            AuditResult(
                check_id="GST_02", focus="GSTIN format", rule="Must be 15 chars",
                compliance_status="NON_COMPLIANT", evidence="gstin = null",
                violation_details="GSTIN is missing", suggested_amendment="Add GSTIN"
            )
        ]
    }
    
    # Test 1: Dict-based
    buffer = _generate_audit_pdf("TestDocument.pdf", "Test risk report with Unicode: Rs.100", audit_state)
    data = buffer.read()
    print(f"Test 1 (dict): Buffer={len(data)} bytes, Valid PDF={data.startswith(b'%PDF')}")
    
    # Test 2: Pydantic-based
    buffer2 = _generate_audit_pdf("PydanticTest.pdf", "Test Pydantic objects", pydantic_state)
    data2 = buffer2.read()
    print(f"Test 2 (Pydantic): Buffer={len(data2)} bytes, Valid PDF={data2.startswith(b'%PDF')}")
    
    # Test 3: Empty state
    buffer3 = _generate_audit_pdf("Empty.pdf", "", {})
    data3 = buffer3.read()
    print(f"Test 3 (empty): Buffer={len(data3)} bytes, Valid PDF={data3.startswith(b'%PDF')}")

if __name__ == "__main__":
    test_pdf()
