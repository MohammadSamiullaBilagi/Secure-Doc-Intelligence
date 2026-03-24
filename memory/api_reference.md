# API Reference

Base URL: `http://localhost:8000`
Auth header: `Authorization: Bearer <jwt_token>` (all endpoints except register/login)
Login sends `application/x-www-form-urlencoded` with field `username` (= email) + `password`

## Auth — `/api/v1/auth`
| Method | Path | Body | Response | Notes |
|--------|------|------|----------|-------|
| POST | /register | `{email, password}` JSON | 201 `{id, email, is_active, created_at}` | |
| POST | /login | form-urlencoded `username=email&password=...` | `{access_token, token_type}` | |
| POST | /google | `{credential: google_id_token}` JSON | `{access_token, token_type}` | |
| GET | /me | — | `{id, user_id, email, is_active, created_at}` | |

## Documents — `/api/v1/documents`
| Method | Path | Body | Response | Notes |
|--------|------|------|----------|-------|
| POST | /upload | multipart: `files[]`, `blueprint_file` (str, default "gst_blueprint.json") | `{message, documents[], thread_ids[], status}` | 5 credits/PDF |
| POST | /bulk-upload | multipart: `files[]`, `client_names` (comma-sep str), `blueprint_file` | `{results: [{file_name, client_name, thread_id, status:"queued"}]}` | Enterprise only, 5 credits/PDF, 402 if insufficient |

## Chat — `/api/v1/chat`
| Method | Path | Body | Response | Notes |
|--------|------|------|----------|-------|
| POST | (empty) | `{message, target_document?}` JSON | `{answer, citations[]}` | 1 credit |

## Audits — `/api/v1/audits`
| Method | Path | Body | Response | Notes |
|--------|------|------|----------|-------|
| GET | /pending | — | `[{thread_id, document_name, risk_report, requires_action, email_draft?}]` | |
| DELETE | /clear | — | `{status, cleared}` | Deletes all pending jobs |
| POST | /{thread_id}/approve | `{edited_draft: str}` | `{status, message}` | Resumes LangGraph |
| POST | /{thread_id}/reject | — | `{status, message}` | Cancels thread |

## Blueprints — `/api/v1/blueprints`
| Method | Path | Body | Response | Notes |
|--------|------|------|----------|-------|
| GET | (empty) | — | `[{id, name, description, checks_count, is_system}]` | System + user blueprints |
| POST | (empty) | `{name, description, checks: [{check_id, focus, rule}]}` | `{id, name, description, checks_count, message}` | 2 credits |
| DELETE | /{blueprint_id} | — | `{message}` | Cannot delete system blueprints |

## Reports — `/api/v1/reports`
| Method | Path | Query | Response | Notes |
|--------|------|-------|----------|-------|
| GET | /{thread_id}/pdf | — | PDF binary stream | All plans |
| GET | /{thread_id}/export | `?format=csv\|tally\|zoho` | Binary file stream | Enterprise only |

Export media types: csv=`text/csv`, tally=`application/xml`, zoho=`application/json`
All binary downloads: parse `Content-Disposition` header for filename.

## Status — `/api/v1/status`
| Method | Path | Response | Notes |
|--------|------|----------|-------|
| GET | /stream/{thread_id} | SSE stream | Events: `status` `{stage, message, progress}`, `done`, `error`, `timeout` |
| GET | /{thread_id} | `{stage, message, progress}` | Single poll |

SSE stages: `queued` → `researching` → `auditing` → `analyzing` → `remediating` → `awaiting_review` → `completed` \| `error`

## Billing — `/api/v1/billing`
| Method | Path | Response |
|--------|------|----------|
| GET | /balance | `{plan, credits_balance, credits_monthly_quota, total_actions_taken, is_active}` |
| GET | /transactions?limit=20 | `[{action, credits_delta, credits_after, description, timestamp}]` |
| GET | /plans | `[{id, name, credits, price_inr, price_label}]` |
| POST | /upgrade | body `{plan, razorpay_subscription_id?}` → `{plan, credits_balance, credits_added}` |
| POST | /topup | body `{amount: int}` → `{message, new_balance}` |

## Payments — `/api/v1/payments`
| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | /create-order | `{plan}` | `{order_id, amount, currency, plan, razorpay_key_id}` |
| POST | /verify | `{razorpay_order_id, razorpay_payment_id, razorpay_signature, plan}` | `{status, message, plan, credits_balance, credits_added}` |
| POST | /create-topup-order | `{credits: int}` | `{order_id, amount, currency, credits, razorpay_key_id}` |
| POST | /verify-topup | `{razorpay_order_id, razorpay_payment_id, razorpay_signature, credits}` | `{status, message, credits_added, new_balance}` |
| POST | /webhook | Razorpay server-to-server | `{status: "ok"}` |

## Clients — `/api/v1/clients` (Enterprise only)
| Method | Path | Body / Query | Response |
|--------|------|--------------|----------|
| GET | / | `?search=term` (optional) | `[{id, name, gstin, email, phone, created_at, document_count}]` |
| POST | / | `{name, gstin?, email?, phone?}` | 201 `{id, name, gstin, email, phone, created_at, document_count:0}` |
| PUT | /{client_id} | `{name?, gstin?, email?, phone?}` | `{...updated client...}` |
| DELETE | /{client_id} | — | 204 No Content |
| GET | /{client_id}/documents | — | `[{id, document_name, audit_job_id, created_at}]` |

Error for duplicate client name per CA: 500 (IntegrityError from UniqueConstraint on ca_user_id+name).

## Calendar — `/api/v1/calendar` (Enterprise only)
| Method | Path | Query / Body | Response |
|--------|------|--------------|----------|
| GET | /deadlines | `?days_ahead=30` (1–365) | `[{id, title, due_date, category, description, days_remaining}]` |
| POST | /reminders | `{deadline_id, remind_days_before:3, channel:"email"\|"whatsapp"}` | 201 `{id, deadline:{...}, remind_days_before, channel, is_active, created_at}` |
| GET | /reminders | — | `[{id, deadline:{...}, remind_days_before, channel, is_active, created_at}]` |
| DELETE | /reminders/{reminder_id} | — | 204 No Content |

Deadline categories: `"GST"`, `"TDS"`, `"Income Tax"`, `"Advance Tax"`
Reminder errors: 404 if deadline not found, 409 if reminder already exists for that deadline.

## Notices — `/api/v1/notices`
| Method | Path | Body / Query | Response | Notes |
|--------|------|--------------|----------|-------|
| POST | /upload | multipart: `file`, `notice_type` | `{id, notice_type, status, ...}` | 5 credits |
| GET | /{notice_id} | — | Notice details + AI reply | |
| POST | /{notice_id}/regenerate | — | Regenerated reply | 1 credit |

## GST Reconciliation — `/api/v1/gst-recon`
| Method | Path | Body / Query | Response | Notes |
|--------|------|--------------|----------|-------|
| POST | /upload | multipart: `purchase_file`, `gstr2b_file` | `{recon_id, status, ...}` | 10 credits |
| GET | /{recon_id} | — | Full reconciliation results | |
| GET | /{recon_id}/report | — | PDF binary stream | |
| GET | /{recon_id}/csv | `?sheet=Matched\|Value Mismatches\|Missing In Books\|Missing In GSTR-2B` | CSV file | Per-table |
| GET | /{recon_id}/excel | — | Multi-sheet XLSX | All tables |

## GSTR-9 Reconciliation — `/api/v1/gstr9-recon`
| Method | Path | Body / Query | Response | Notes |
|--------|------|--------------|----------|-------|
| POST | /upload | multipart: files | `{recon_id, status, ...}` | 15 credits |
| GET | /{recon_id} | — | Full reconciliation results | |
| GET | /{recon_id}/report | — | PDF binary stream | |
| GET | /{recon_id}/csv | `?sheet=Monthly Comparison\|Tax Reconciliation\|ITC Summary\|Action Items` | CSV file | Per-table |
| GET | /{recon_id}/excel | — | Multi-sheet XLSX | All tables |

## Bank Statement Analysis — `/api/v1/bank-analysis`
| Method | Path | Body / Query | Response | Notes |
|--------|------|--------------|----------|-------|
| POST | /upload | multipart: `file` | `{analysis_id, status, ...}` | 8 credits |
| GET | /{analysis_id} | — | Full analysis results | |
| GET | /{analysis_id}/report | — | PDF binary stream | |
| GET | /{analysis_id}/csv | `?sheet=Flags\|Transactions` | CSV file | Per-table |
| GET | /{analysis_id}/excel | — | Multi-sheet XLSX | All tables |

## Capital Gains — `/api/v1/capital-gains`
| Method | Path | Body / Query | Response | Notes |
|--------|------|--------------|----------|-------|
| POST | /upload | multipart: `file` | `{analysis_id, status, ...}` | 10 credits |
| GET | /{analysis_id} | — | Full analysis results | |
| GET | /{analysis_id}/report | — | PDF binary stream | |
| GET | /{analysis_id}/csv | `?sheet=Transactions\|Schedule CG\|ITR Values` | CSV file | Per-table |
| GET | /{analysis_id}/excel | — | Multi-sheet XLSX | All tables |

## Depreciation — `/api/v1/depreciation`
| Method | Path | Body / Query | Response | Notes |
|--------|------|--------------|----------|-------|
| POST | /upload | multipart: `file` | `{analysis_id, status, ...}` | 8 credits |
| GET | /{analysis_id} | — | Full analysis results | |
| GET | /{analysis_id}/report | — | PDF binary stream | |
| GET | /{analysis_id}/csv | `?sheet=IT Act Blocks\|Companies Act Assets\|Deferred Tax` | CSV file | Per-table |
| GET | /{analysis_id}/excel | — | Multi-sheet XLSX | All tables |

## Advance Tax — `/api/v1/advance-tax`
| Method | Path | Body / Query | Response | Notes |
|--------|------|--------------|----------|-------|
| POST | /compute | body JSON | `{computation_id, status, ...}` | 2 credits |
| GET | /{computation_id} | — | Full computation results | |
| GET | /{computation_id}/report | — | PDF binary stream | |
| GET | /{computation_id}/csv | `?sheet=Instalments\|Interest Summary` | CSV file | Per-table |
| GET | /{computation_id}/excel | — | Multi-sheet XLSX | All tables |

## Feedback — `/api/v1/feedback`
| Method | Path | Body | Response |
|--------|------|------|----------|
| POST | / | `{rating: 1-5, message?, feature?}` | `{id, message}` |

## Feature Access — `/api/v1/billing/feature-access`
| Method | Path | Response |
|--------|------|----------|
| GET | /feature-access | `{features: {key: {accessible, label, min_plan, credit_gated, upgrade_to?}}}` |

Feature keys: `gstr2b_recon`, `gstr9_recon`, `bank_analysis`, `capital_gains`, `depreciation`, `advance_tax`, `notice_reply`, `blueprints`, `client_management`, `tax_calendar`, `bulk_upload`, `export`

## Health Check
| Method | Path | Response |
|--------|------|----------|
| GET | /health | `{status: "ok"\|"degraded", service, env, database, vector_db}` — returns 503 if degraded |

## Common Error Shapes
```json
// 401 Unauthorized
{"detail": "Could not validate credentials"}

// 402 Insufficient credits
{"detail": {"error": "Insufficient credits", "required": 5, "balance": 3, "action": "document_scan", "plan": "free_trial"}}

// 403 Enterprise required
{"detail": {"error": "Enterprise plan required", "message": "...", "current_plan": "free_trial", "required_plan": "enterprise"}}

// 409 Duplicate reminder
{"detail": "Reminder already exists for this deadline"}

// 422 Validation error (Pydantic)
{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}
```
