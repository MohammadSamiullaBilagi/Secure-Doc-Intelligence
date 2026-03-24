from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_user
from db.database import get_db
from db.models.core import User
from db.models.billing import CreditActionType
from agent import SecureDocAgent
from services.credits_service import CreditsService
from api.rate_limit import limiter
from api.routes.documents import get_session_paths

router = APIRouter(prefix="/api/v1/chat", tags=["chat"])

class ChatRequest(BaseModel):
    message: str
    target_document: Optional[str] = "All Documents"

class ChatResponse(BaseModel):
    answer: str
    citations: list[str]

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
    db: AsyncSession = Depends(get_db)
):
    """Answers legal queries based on the user's isolated document database."""
    _, db_dir = get_session_paths(str(current_user.id))
    
    if not db_dir.exists() or not any(db_dir.iterdir()):
        raise HTTPException(status_code=400, detail="Database is empty. Please upload documents first.")

    # Deduct 1 credit for chat query
    await CreditsService.check_and_deduct(
        current_user.id,
        CreditActionType.CHAT_QUERY,
        db,
        description=f"Chat: {body.message[:50]}"
    )

    metadata_filter = None
    if body.target_document and body.target_document != "All Documents":
        metadata_filter = {"source": body.target_document}

    try:
        agent = SecureDocAgent(db_dir=str(db_dir))
        result = agent.query(question=body.message, metadata_filter=metadata_filter)
        
        return ChatResponse(
            answer=result["answer"],
            citations=result["citations"]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
