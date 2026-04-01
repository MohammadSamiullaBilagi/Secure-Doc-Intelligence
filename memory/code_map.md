---
name: Complete Code Map
description: Every class, method, endpoint, and schema with signatures — eliminates need to explore codebase
type: reference
---

# Complete Code Map — Legal AI Expert

## 1. CORE PIPELINES

### agent.py — SecureDocAgent (RAG Pipeline)
| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(db_dir='vector_db', global_db_dir='global_vector_db')` | Init embeddings, ChromaDB, LLM |
| `query` | `(question: str, metadata_filter: dict=None) -> dict` | Returns {answer, citations} |
| `extract_for_audit` | `(focus_query: str, rule: str, metadata_filter: dict=None) -> str` | Direct extraction, no hallucination check |
| `extract_structured_fields` | `(blueprint_dict: dict, metadata_filter: dict=None, data_dir: str=None) -> dict` | 4-stage: ChromaDB→PDF→OCR→LLM→JSON |
| `extract_notice_fields` | `(blueprint_dict: dict, metadata_filter: dict=None, data_dir: str=None) -> dict` | Notice-specific extraction |

Internal nodes: `route_query_node`, `retrieve_node`, `generate_node`, `evaluate_node`, `fallback_node`, `route_evaluation`
State: `AgentState(TypedDict)` — question, metadata_filter, target_db, context, answer, retries, is_hallucination

### multi_agent.py — ComplianceOrchestrator (5-stage Audit)
| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(db_dir: str, data_dir: str="")` | Init LLM, SecureDocAgent |
| `run_blueprint_audit` | `(target_contract, blueprint, session_hash, user_id, thread_id=None) -> MultiAgentState` | Main entry |
| `get_compiled_graph` | `() -> CompiledGraph` | With SqliteSaver + interrupt_before=["dispatch"] |

Nodes: `researcher_node` (L1 parse) → `auditor_node` (L2 parallel checks) → `analyst_node` (L3 risk report) → `remediation_node` (email draft) → `dispatch_node` (webhook)
State: `MultiAgentState` — session_hash, user_id, thread_id, data_dir, target_contract, blueprint, extracted_fields, audit_results, risk_report, remediation_draft, status

### ingestion.py — DocumentProcessor
| Method | Signature | Description |
|--------|-----------|-------------|
| `__init__` | `(data_dir="data", db_dir="vector_db")` | Init paths, splitter (1000/150), hash cache |
| `extract_text_from_pdfs` | `(only_files: list=None) -> List[Document]` | PyMuPDF→OCR fallback |
| `create_vector_store` | `(documents: List[Document]) -> None` | Chunk + embed + ChromaDB |

---

## 2. API DEPENDENCIES — api/dependencies.py
| Function | Description |
|----------|-------------|
| `get_current_user(token, db) -> User` | JWT decode → User lookup, 401 if invalid |
| `require_starter(user, db) -> User` | 403 if not starter/professional/enterprise |
| `require_professional(user, db) -> User` | 403 if not professional/enterprise |
| `require_enterprise(user, db) -> User` | 403 if not enterprise |

---

## 3. API ROUTES

### auth.py — /api/v1/auth
| Endpoint | Method | Body | Response | Notes |
|----------|--------|------|----------|-------|
| /register | POST | `{email, password}` | 201 UserResponse | Rate limited: 10/min |
| /login | POST | form `username=email&password=...` | Token | Rate limited: 10/min |
| /json-login | POST | `{email, password}` | Token | Rate limited: 10/min |
| /google | POST | `{credential}` (param name: `body`) | Token | Rate limited: 10/min. `request` param is FastAPI Request for rate limiter |
| /me | GET | — | {id, email, is_active, created_at} | |
| /preferences | GET | — | UserPreference fields | |
| /preferences | PUT | UpdatePreferencesRequest | Updated prefs | |

### documents.py — /api/v1/documents
| Endpoint | Method | Body | Response | Plan |
|----------|--------|------|----------|------|
| /upload | POST | files[], blueprint_file, client_id? | {documents, thread_ids, status} | All (3 credits/PDF) |
| /bulk-upload | POST | files[], client_names, blueprint_file | {results[]} | Enterprise (3 credits/PDF) |

Helper: `get_session_paths(user_id) -> (data_dir, db_dir)`

### chat.py — /api/v1/chat
| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| /starters | GET | — | suggested prompts |
| / | POST | `{message, target_document?}` | {answer, citations} (1 credit) |

### audits.py — /api/v1/audits
| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| /pending | GET | — | List[PendingAuditResponse] |
| /clear | DELETE | — | {status, cleared} |
| /{thread_id}/approve | POST | {edited_draft} | {status, message, email_sent, email_error} — sends email to client via EmailService |

Note: `GET /pending` returns `email_draft` (raw with \n) AND `email_draft_html` (with `<br>` tags) — frontend should use the `_html` field for display.
| /{thread_id}/reject | POST | — | {status, message} |

### blueprints.py — /api/v1/blueprints (Professional+ / free_trial with credits)
| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| /access | GET | — | {has_access, reason, plan, credits_balance} — frontend calls this to decide blueprint selector vs upgrade prompt |
| / | GET | — | [{id, name, description, checks_count, is_system}] |
| / | POST | {name, description, checks[]} | {id, name, checks_count} (2 credits) |
| /{blueprint_id} | DELETE | — | {message} |

### reports.py — /api/v1/reports
| Endpoint | Method | Query | Response | Plan |
|----------|--------|-------|----------|------|
| /{thread_id}/pdf | GET | — | PDF stream | All |
| /{thread_id}/export | GET | format=csv\|tally\|zoho | Binary stream | Enterprise |

### notices.py — /api/v1/notices (Professional+)
| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| /upload | POST | notice_file, notice_type, client_id?, supporting_files | {notice_job_id, status} (5 credits) |
| / | GET | — | List[NoticeListItem] |
| /{job_id} | GET | — | NoticeDetailResponse |
| /{job_id}/approve | POST | {edited_draft} | {message, status, email_sent, email_error} — sends email to client via EmailService |

Note: `GET /{job_id}` returns `draft_reply_html` and `final_reply_html` (with `<br>` tags) alongside raw text fields — frontend should use `_html` fields for display.
| /{job_id}/regenerate | POST | — | — (1 credit) |

### clients.py — /api/v1/clients (Enterprise)
| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| / | GET | search? | List[ClientResponse] |
| / | POST | ClientCreate | ClientResponse |
| /{client_id} | PUT | ClientUpdate | ClientResponse |
| /{client_id} | DELETE | — | — |
| /{client_id}/documents | GET | — | List[ClientDocumentResponse] |
| /{client_id}/dashboard | GET | — | ClientDashboardItem |

### calendar.py — /api/v1/calendar (Enterprise)
| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| /deadlines | GET | fy?, category? | List[TaxDeadline] |
| /deadlines/{id}/remind | POST | channels | — |
| /sync | GET | — | re-seed |

### billing.py — /api/v1/billing
| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| /balance | GET | — | {plan, credits_balance, credits_monthly_quota, total_actions_taken} |
| /transactions | GET | limit? | List[CreditTransaction] |
| /upgrade | POST | {new_plan} | — |

### payments.py — /api/v1/payments
| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| /create-order | POST | amount, plan? | {order_id, key_id, amount} |
| /verify | POST | {order_id, payment_id, signature} | success |
| /webhook | POST | Razorpay callback | — |

### gst_reconciliation.py — /api/v1/gst-recon
| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| /upload | POST | gstr2b_file, purchase_register_file, period, client_id? | — (10 credits) |
| /{recon_id} | GET | — | recon result |

### bank_analysis.py — /api/v1/bank-analysis
| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| /upload | POST | bank_statement_file, period_from, period_to, client_id? | — (8 credits) |
| /{analysis_id} | GET | — | analysis result |

### capital_gains.py — /api/v1/capital-gains
| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| /upload | POST | broker_statement_file, fy, client_id? | — (10 credits) |
| /{analysis_id} | GET | — | {total_transactions, total_gain_loss, schedule_cg} |

### depreciation.py — /api/v1/depreciation
| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| /calculate | POST | asset_file, fy, method (WDV/SL), client_id? | — (8 credits) |
| /{calc_id} | GET | — | {assets[], total_depreciation, schedule_fa_json} |

### advance_tax.py — /api/v1/advance-tax
| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| /calculate | POST | income_data, fy, filing_status, client_id? | — (2 credits) |

### gstr9_recon.py — /api/v1/gstr9-recon
| Endpoint | Method | Body | Response |
|----------|--------|------|----------|
| /upload | POST | gstr3b_json, gstr1_json, annual_turnover, client_id? | — (15 credits) |

### status.py — /api/v1/status
| Endpoint | Method | Description |
|----------|--------|-------------|
| GET /{thread_id} | GET | Returns {stage, progress_percent, message} |
| POST /{thread_id} | POST | Internal: updates status |

Helper: `update_audit_status(thread_id, stage, message, progress)` — called by WatcherService

---

## 4. DATABASE MODELS

### db/models/core.py
- **User**: id(Uuid), email(unique), hashed_password(nullable), is_active, created_at, updated_at. Rels: preferences(1:1), blueprints(1:M), audit_jobs(1:M), clients(1:M), notice_jobs(1:M)
- **UserPreference**: user_id(fk), preferred_email, whatsapp_number, alert_tier, firm_name, ca_name, icai_membership_number, firm_address, firm_phone, firm_email
- **Blueprint**: user_id(fk, nullable=system), name, description, rules_json(JSON)
- **AuditJob**: user_id(fk), document_name, status(pending/approved/rejected/dispatched), langgraph_thread_id(indexed), client_id(fk?), results_summary(JSON), blueprint_name, compliance_score, open_violations, total_financial_exposure
- **GSTReconciliation**: user_id, client_id?, period, status, result_json, matched/mismatched/missing counts, total_itc_available/at_risk
- **BankStatementAnalysis**: user_id, client_id?, filename, period_from/to, status, result_json, totals, flags_count
- **CapitalGainsAnalysis**: user_id, client_id?, filename, fy, status, result_json, total_transactions, total_gain_loss

### db/models/billing.py
- **PlanTier** enum: FREE_TRIAL, STARTER, PROFESSIONAL, ENTERPRISE, PAY_AS_YOU_GO
- **CreditActionType** enum: DOCUMENT_SCAN(3), CHAT_QUERY(1), BLUEPRINT_CREATE(2), NOTICE_REPLY(5), NOTICE_REGENERATE(1), GSTR_RECON(10), BANK_ANALYSIS(8), CAPITAL_GAINS_ANALYSIS(10), GSTR9_RECON(15), DEPRECIATION_CALC(8), ADVANCE_TAX_CALC(2)
- **Subscription**: user_id(unique), plan, credits_balance, credits_monthly_quota, billing_cycle_start, razorpay_subscription_id?, is_active
- **CreditTransaction**: user_id, action, credits_delta, credits_after, description

### db/models/clients.py
- **Client**: ca_user_id(fk), name, gstin?, email?, phone?. UniqueConstraint(ca_user_id, name)
- **ClientDocument**: client_id(fk), audit_job_id(fk), document_name

### db/models/calendar.py
- **TaxDeadline**: fy, category(GST/IT/TDS/etc), deadline_date, description, section_reference

### db/models/notices.py
- **NoticeJob**: user_id, client_id?, notice_type(143_1/148/drc01), notice_document_name, supporting_documents(JSON), status, langgraph_thread_id, generated_draft(JSON)

### db/models/references.py
- **ReferenceCache**: check_id(indexed), cached_rules, source_name, source_url?, confidence, cached_at, ttl_days

---

## 5. SCHEMAS (Pydantic)

### schemas/user.py
UserCreate(email, password), UserResponse(id, email, is_active, created_at), Token(access_token, token_type), TokenData(user_id?), LoginRequest(email, password), UpdatePreferencesRequest(all optional CA fields)

### schemas/blueprint_schema.py
BlueprintCheck(check_id, focus, rule), Blueprint(blueprint_id, name, description, checks[]), AuditResult(check_id, focus, rule, compliance_status, evidence, violation_details, suggested_amendment), FinancialImpact(estimated_amount?, currency=INR, calculation, section_reference), CheckAgentOutput(+financial_impact, confidence), EnhancedAuditResult(+financial_impact, confidence, reference_source, reference_url)

### schemas/client_schema.py
ClientCreate(name, gstin?, email?, phone?), ClientUpdate(all optional), ClientResponse(+document_count), ClientDocumentResponse, ClientDashboardItem(audit_count, pending_audits, total_violations, total_exposure)

### schemas/notice_schema.py
NoticeUploadResponse(notice_job_id, status, message), NoticeDetailResponse(job_id, notice_type, generated_draft, status), NoticeListItem, NoticeApproveRequest(edited_draft)

### schemas/export_schema.py
ExportFormat enum: CSV, TALLY, ZOHO

---

## 6. SERVICES

### services/credits_service.py — CreditsService
`get_or_create_subscription(user_id, db)`, `check_and_deduct(user_id, action, db)` (402 if insufficient), `add_credits(user_id, amount, action, db)`, `get_balance(user_id, db)`, `upgrade_plan(user_id, new_plan, db)`

### services/auth_service.py
`verify_password(plain, hashed)`, `get_password_hash(password)`, `create_access_token(data, expires_delta=1week)`

### services/watcher_service.py
`_resolve_blueprint(blueprint_file) -> Blueprint`, `run_background_audit(session_hash, filename, blueprint_file, user_id, thread_id)`, `_store_audit_results(thread_id, final_state, blueprint_name)`

### services/document_parser.py — DocumentParser
`parse_document(combined_text) -> dict` (company_info, metadata, parties, line_items, tables, sections, totals), `parse_document_chunked(text)` (for >24k chars)

### services/check_agent.py — CheckAgentService
`evaluate_check(parsed_doc, check, reference) -> CheckAgentOutput`, `evaluate_all_checks(parsed_doc, checks) -> List[CheckAgentOutput]` (parallel via asyncio.gather)

### services/reference_service.py — ReferenceService
`lookup_reference(check) -> ReferenceResult` (Tavily + ReferenceCache with TTL)

### services/blueprint_service.py — BlueprintService
`load_blueprint(filename) -> Blueprint`, `get_available_blueprints() -> list[str]`, `seed_system_blueprints(db)`

### services/approval_service.py — ApprovalService
`get_pending_approval(thread_id) -> dict?`, `approve_and_resume(thread_id, edited_email)`, `reject_and_cancel(thread_id)`

### services/notice_service.py — NoticeService
`process_notice(job_id, db_dir, data_dir, thread_id)`

### services/report_service.py — ReportService
`compute_compliance_score(state) -> (float, int)`, `generate_compliance_pdf(doc_name, risk_report, state, client_info?, ca_info?) -> BytesIO`

### services/export_service.py — ExportService
`to_csv(results) -> BytesIO`, `to_tally_xml(results) -> BytesIO`, `to_zoho_json(results) -> BytesIO`

### services/calendar_service.py — CalendarService
`seed_indian_deadlines(db)` (idempotent, GST/IT/TDS/FEMA)

### services/email_service.py — EmailService
`is_configured() -> bool`, `send_email(to, subject, body_html, ca_name?, reply_to?) -> bool` (sends both plain+HTML parts), `send_deadline_reminder(to, ca_name, deadline_name, due_date_str, days_remaining, reply_to?)`, `send_audit_dispatch(to, ca_name, subject, body, reply_to?)`, `send_notice_reply(to, notice_type_display, reply_body, ca_name?, firm_name?, reply_to?)`
Multi-tenant: FROM=platform verified address, display name="CA Name via Legal AI Expert", Reply-To=CA's email. Uses SMTP (SendGrid compatible).

### services/webhook_service.py — WebhookService
`dispatch_audit_results(session_hash, filename, final_state)` (N8N webhook)

### services/bank_statement_service.py, capital_gains_service.py, depreciation_service.py, gstr2b_reconciliation_service.py, gstr9_reconciliation_service.py, advance_tax_service.py
Specialized calculation/analysis services for respective features

---

## 7. CONFIG & STARTUP

### config.py — Settings
database_url, openai_api_key, anthropic_api_key, tavily_api_key, session_ttl_hours(48), global_db_dir, user_sessions_dir, checkpointer_db_path, n8n_webhook_url, smtp_*, razorpay_key_id, razorpay_key_secret

### main.py — FastAPI App
- CORS: allow_origins=["*"]
- Middleware: request logging
- Startup: create tables, seed calendar, seed blueprints
- Health: GET /health → {"status": "ok"}
- All routers registered with /api/v1/ prefix

### db/database.py
Base, TimestampMixin(created_at, updated_at), engine(async SQLite or PostgreSQL), AsyncSessionLocal, get_db()
PostgreSQL pool: pool_size=5, max_overflow=10, pool_pre_ping=True, pool_recycle=1800, pool_timeout=30 (db-f1-micro max 25 conns)
