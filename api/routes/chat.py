import uuid
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from api.dependencies import get_current_user
from db.database import get_db
from db.models.core import User
from db.models.billing import CreditActionType
from db.models.chat import ChatMessage
from agent import SecureDocAgent
from services.credits_service import CreditsService
from api.rate_limit import limiter
from api.routes.documents import get_session_paths

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str
    target_document: Optional[str] = "All Documents"
    session_id: Optional[str] = None  # For conversation continuity


class ChatResponse(BaseModel):
    answer: str
    citations: list[str]
    session_id: str  # Returned so frontend can track the session


@router.get("/starters")
async def get_chat_starters():
    """Return suggested prompt starters for the chat interface."""
    return {
        "starters": [
            "What are all cash payments above Rs.10,000 in this document?",
            "Is TDS deducted on all professional fee payments?",
            "What is the total ITC claimed and is it eligible?",
            "Are there any MSME vendors with payment beyond 45 days?",
        ]
    }


@router.post("", response_model=ChatResponse)
@limiter.limit("30/minute")
async def chat_with_agent(
    request: Request,
    body: ChatRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
):
    """Answers legal queries based on the user's documents or general knowledge."""
    _, db_dir = get_session_paths(str(current_user.id))

    # Deduct 1 credit for chat query
    await CreditsService.check_and_deduct(
        current_user.id,
        CreditActionType.CHAT_QUERY,
        db,
        description=f"Chat: {body.message[:50]}",
    )

    # Session management — generate or reuse session_id
    session_id = body.session_id or str(uuid.uuid4())

    # Load conversation history (last 10 messages for this session)
    chat_history = []
    try:
        result = await db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.user_id == current_user.id,
                ChatMessage.session_id == session_id,
            )
            .order_by(desc(ChatMessage.created_at))
            .limit(10)
        )
        history_rows = result.scalars().all()
        # Reverse to chronological order (oldest first)
        for msg in reversed(history_rows):
            chat_history.append({"role": msg.role, "content": msg.content})
    except Exception as e:
        # Don't fail the chat if history loading fails
        import logging
        logging.getLogger(__name__).warning(f"Failed to load chat history: {e}")

    metadata_filter = None
    if body.target_document and body.target_document != "All Documents":
        metadata_filter = {"source": body.target_document}

    try:
        # Ensure db_dir exists even if empty (agent handles empty vectorstore gracefully)
        if db_dir and not db_dir.exists():
            db_dir.mkdir(parents=True, exist_ok=True)

        agent = SecureDocAgent(db_dir=str(db_dir))
        result = agent.query(
            question=body.message,
            metadata_filter=metadata_filter,
            chat_history=chat_history,
        )

        answer = result["answer"]
        citations = result["citations"]

        # Save user message and assistant response to DB
        try:
            user_msg = ChatMessage(
                user_id=current_user.id,
                session_id=session_id,
                role="user",
                content=body.message,
                target_document=body.target_document,
            )
            assistant_msg = ChatMessage(
                user_id=current_user.id,
                session_id=session_id,
                role="assistant",
                content=answer,
                target_document=body.target_document,
            )
            db.add(user_msg)
            db.add(assistant_msg)
            await db.commit()
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(f"Failed to save chat history: {e}")

        return ChatResponse(
            answer=answer,
            citations=citations,
            session_id=session_id,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
