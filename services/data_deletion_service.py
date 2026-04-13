"""Right to Erasure service — DPDPA Section 12 compliance.

Deletes all personal data for a user while preserving:
- User account record (marked with data_deleted_at)
- Subscription (billing history)
- CreditTransaction (financial audit trail)
- AuditLog (compliance records — retention justified under DPDPA Section 8(8))
"""

import logging
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.core import (
    AuditJob, Blueprint, User,
    GSTReconciliation, BankStatementAnalysis, CapitalGainsAnalysis,
    DepreciationAnalysis, AdvanceTaxComputation, GSTR9Reconciliation,
)
from db.models.chat import ChatMessage
from db.models.clients import Client, ClientDocument
from db.models.notices import NoticeJob
from db.models.calendar import UserReminder
from db.models.feedback import Feedback
from db.models.password_reset import PasswordResetToken
from db.config import settings
from services.storage import get_storage

logger = logging.getLogger(__name__)


async def delete_user_data(user_id: uuid.UUID, db: AsyncSession) -> dict:
    """Delete all personal data for a user. Returns summary of deleted counts."""
    summary = {}

    # 1. ChatMessage
    result = await db.execute(delete(ChatMessage).where(ChatMessage.user_id == user_id))
    summary["chat_messages"] = result.rowcount

    # 2. Feedback
    result = await db.execute(delete(Feedback).where(Feedback.user_id == user_id))
    summary["feedback"] = result.rowcount

    # 3. UserReminder
    result = await db.execute(delete(UserReminder).where(UserReminder.user_id == user_id))
    summary["reminders"] = result.rowcount

    # 4. PasswordResetToken
    result = await db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user_id))
    summary["password_tokens"] = result.rowcount

    # 5. ClientDocument (must come before Client due to FK)
    clients_result = await db.execute(select(Client.id).where(Client.ca_user_id == user_id))
    client_ids = [row[0] for row in clients_result.all()]
    if client_ids:
        result = await db.execute(delete(ClientDocument).where(ClientDocument.client_id.in_(client_ids)))
        summary["client_documents"] = result.rowcount
    else:
        summary["client_documents"] = 0

    # 6. Client
    result = await db.execute(delete(Client).where(Client.ca_user_id == user_id))
    summary["clients"] = result.rowcount

    # 7. NoticeJob
    result = await db.execute(delete(NoticeJob).where(NoticeJob.user_id == user_id))
    summary["notice_jobs"] = result.rowcount

    # 8. All analysis models
    for model, key in [
        (GSTReconciliation, "gst_reconciliations"),
        (BankStatementAnalysis, "bank_analyses"),
        (CapitalGainsAnalysis, "capital_gains"),
        (DepreciationAnalysis, "depreciation"),
        (AdvanceTaxComputation, "advance_tax"),
        (GSTR9Reconciliation, "gstr9_reconciliations"),
    ]:
        result = await db.execute(delete(model).where(model.user_id == user_id))
        summary[key] = result.rowcount

    # 9. AuditJob
    result = await db.execute(delete(AuditJob).where(AuditJob.user_id == user_id))
    summary["audit_jobs"] = result.rowcount

    # 10. Blueprint (user-created only; system blueprints have user_id=None)
    result = await db.execute(delete(Blueprint).where(Blueprint.user_id == user_id))
    summary["blueprints"] = result.rowcount

    # 11. Delete uploaded files via storage backend
    try:
        storage = get_storage()
        storage.delete_prefix(f"{user_id}/")
        summary["files_deleted"] = True
    except Exception as e:
        logger.warning(f"File deletion failed for user {user_id}: {e}")
        summary["files_deleted"] = False

    # 12. Delete ChromaDB vector store directory
    vector_db_path = Path(settings.USER_SESSIONS_DIR) / str(user_id) / "vector_db"
    user_session_path = Path(settings.USER_SESSIONS_DIR) / str(user_id)
    try:
        if vector_db_path.exists():
            shutil.rmtree(vector_db_path)
        if user_session_path.exists():
            shutil.rmtree(user_session_path)
        summary["vector_db_deleted"] = True
    except Exception as e:
        logger.warning(f"ChromaDB cleanup failed for user {user_id}: {e}")
        summary["vector_db_deleted"] = False

    # 13. Mark user record as data-deleted
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one()
    user.data_deleted_at = datetime.now(timezone.utc)

    await db.commit()
    logger.info(f"Data deletion completed for user {user_id}: {summary}")
    return summary
