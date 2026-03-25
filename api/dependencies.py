import uuid as _uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from jose import JWTError, jwt
from typing import Annotated

from db.config import settings
from db.database import get_db
from db.models.core import User
from db.models.billing import Subscription
from schemas.user import TokenData
from services.credits_service import CreditsService

# OAuth2 scheme configures Swagger UI to send token to /auth/login
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/login")

async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)]
) -> User:
    """Dependency injection to resolve the active User from the JWT Bearer Token."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Decode the JWT token
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        token_data = TokenData(user_id=user_id)
    except JWTError:
        raise credentials_exception

    # Convert user_id string back to a UUID object for the SQLAlchemy Uuid column
    try:
        uid = _uuid.UUID(token_data.user_id)
    except ValueError:
        raise credentials_exception

    # Query the database for the user UUID
    query = select(User).where(User.id == uid)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    
    if user is None:
        raise credentials_exception

    return user


async def require_admin(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Dependency that enforces admin-only access."""
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


async def require_starter(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Dependency that enforces Starter plan or above.

    Admin users and free trial users with remaining credits are allowed through.
    Returns the user if they are on Starter, Professional, Enterprise,
    or Free Trial with credits > 0.
    """
    # Admins bypass all plan restrictions
    if current_user.is_admin:
        return current_user

    sub = await CreditsService.get_or_create_subscription(current_user.id, db)

    # Free trial users with credits can access all features
    if sub.plan == "free_trial" and sub.credits_balance > 0:
        return current_user

    if sub.plan not in ("starter", "professional", "enterprise"):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "Starter plan required",
                "message": "Your free trial credits are exhausted. Please upgrade to a Starter plan or above to continue using analysis tools.",
                "current_plan": sub.plan,
                "required_plan": "starter",
            },
        )
    return current_user


async def require_enterprise(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Dependency that enforces Enterprise plan for Phase 3 CA features.

    Admin users and free trial users with remaining credits are allowed through.
    Returns the user if they are on the Enterprise plan, or Free Trial with credits > 0.
    """
    # Admins bypass all plan restrictions
    if current_user.is_admin:
        return current_user

    sub = await CreditsService.get_or_create_subscription(current_user.id, db)

    # Free trial users with credits can access all features
    if sub.plan == "free_trial" and sub.credits_balance > 0:
        return current_user

    if sub.plan != "enterprise":
        raise HTTPException(
            status_code=403,
            detail={
                "error": "Enterprise plan required",
                "message": "This feature is available only on the Enterprise plan. Please upgrade to access Client Management, Bulk Upload, Tax Calendar, and Export features.",
                "current_plan": sub.plan,
                "required_plan": "enterprise",
            },
        )
    return current_user


async def require_professional(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Dependency that enforces Professional or Enterprise plan.

    Admin users and free trial users with remaining credits are allowed through.
    Returns the user if they are on Professional or Enterprise, or Free Trial with credits > 0.
    """
    # Admins bypass all plan restrictions
    if current_user.is_admin:
        return current_user

    sub = await CreditsService.get_or_create_subscription(current_user.id, db)

    # Free trial users with credits can access all features
    if sub.plan == "free_trial" and sub.credits_balance > 0:
        return current_user

    if sub.plan not in ("professional", "enterprise"):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "Professional plan required",
                "message": "Your free trial credits are exhausted. This feature is available on Professional and Enterprise plans. Please upgrade to access it.",
                "current_plan": sub.plan,
                "required_plan": "professional",
            },
        )
    return current_user
