from datetime import timedelta
from typing import Annotated
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.database import get_db
from db.models.core import User, UserPreference
from db.config import settings
from schemas.user import UserCreate, UserResponse, Token, LoginRequest, UpdatePreferencesRequest
from services.auth_service import get_password_hash, verify_password, create_access_token
from api.dependencies import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class GoogleAuthRequest(BaseModel):
    credential: str  # The ID token from Google Identity Services


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register_user(user_in: UserCreate, db: Annotated[AsyncSession, Depends(get_db)]):
    """Registers a new User and seeds their default notification preferences."""
    import traceback
    try:
        # 1. Check if email already exists
        query = select(User).where(User.email == user_in.email)
        result = await db.execute(query)
        existing_user = result.scalar_one_or_none()
        
        if existing_user:
            raise HTTPException(status_code=400, detail="Email already registered")
            
        # 2. Hash password and save new User
        hashed_pwd = get_password_hash(user_in.password)
        new_user = User(email=user_in.email, hashed_password=hashed_pwd)
        
        db.add(new_user)
        await db.flush() # flush to generate the new_user.id UUID
        
        # 3. Create default UserPreference for this User
        default_preferences = UserPreference(
            user_id=new_user.id,
            preferred_email=new_user.email,
            alert_tier="standard"
        )
        db.add(default_preferences)
        
        await db.commit()
        await db.refresh(new_user)
        return new_user
    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}\n\nTraceback:\n{tb}")


@router.post("/login", response_model=Token)
async def login_for_access_token(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """OAuth2 compatible token login, required for Swagger UI integration."""
    
    # 1. Look up User by email (form_data maps generic 'username' binding)
    query = select(User).where(User.email == form_data.username)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Google-only users cannot use password login
    if not user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account uses Google Sign-In. Please sign in with Google.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    # 2. Generate Access Token containing User ID
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id)}, expires_delta=access_token_expires
    )
    
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/json-login", response_model=Token)
async def json_login(
    credentials: LoginRequest,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """JSON-based login endpoint for frontend apps (Lovable, React, etc.)."""

    query = select(User).where(User.email == credentials.email)
    result = await db.execute(query)
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.hashed_password:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This account uses Google Sign-In. Please sign in with Google.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id)}, expires_delta=access_token_expires
    )

    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/google", response_model=Token)
async def google_sign_in(
    request: GoogleAuthRequest,
    db: Annotated[AsyncSession, Depends(get_db)]
):
    """Authenticate via Google ID token. Creates account on first sign-in."""
    from google.oauth2 import id_token
    from google.auth.transport import requests as google_requests
    
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(500, "Google Sign-In is not configured on the server")
    
    # 1. Verify the Google ID token
    try:
        idinfo = id_token.verify_oauth2_token(
            request.credential,
            google_requests.Request(),
            settings.GOOGLE_CLIENT_ID
        )
    except ValueError as e:
        logger.error(f"Google token verification failed: {e}")
        raise HTTPException(401, "Invalid Google credential")
    
    # 2. Extract email from verified token
    email = idinfo.get("email")
    if not email or not idinfo.get("email_verified"):
        raise HTTPException(401, "Google account email not verified")
    
    # 3. Find or create user
    query = select(User).where(User.email == email)
    result = await db.execute(query)
    user = result.scalar_one_or_none()
    
    if not user:
        # First-time Google sign-in — create account (no password)
        user = User(email=email, hashed_password=None)
        db.add(user)
        await db.flush()
        
        # Seed default preferences
        prefs = UserPreference(
            user_id=user.id,
            preferred_email=email,
            alert_tier="standard"
        )
        db.add(prefs)
        await db.commit()
        await db.refresh(user)
        logger.info(f"Created new user via Google Sign-In: {email}")
    
    # 4. Issue our JWT
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id)}, expires_delta=access_token_expires
    )
    
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/me")
async def read_users_me(current_user: Annotated[User, Depends(get_current_user)]):
    """Gets details for the currently authenticated User making the HTTP Request."""
    return {
        "id": str(current_user.id),
        "user_id": str(current_user.id),
        "email": current_user.email,
        "is_active": current_user.is_active,
        "is_admin": current_user.is_admin,
        "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
    }


@router.get("/preferences")
async def get_preferences(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Get current user's preferences including CA branding fields."""
    result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == current_user.id)
    )
    prefs = result.scalar_one_or_none()

    if not prefs:
        return {
            "preferred_email": current_user.email,
            "whatsapp_number": None,
            "firm_name": None,
            "ca_name": None,
            "icai_membership_number": None,
            "firm_address": None,
            "firm_phone": None,
            "firm_email": None,
        }

    return {
        "preferred_email": prefs.preferred_email,
        "whatsapp_number": prefs.whatsapp_number,
        "firm_name": prefs.firm_name,
        "ca_name": prefs.ca_name,
        "icai_membership_number": prefs.icai_membership_number,
        "firm_address": prefs.firm_address,
        "firm_phone": prefs.firm_phone,
        "firm_email": prefs.firm_email,
    }


@router.put("/preferences")
async def update_preferences(
    request: UpdatePreferencesRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Upsert user preferences (notification targets + CA branding)."""
    result = await db.execute(
        select(UserPreference).where(UserPreference.user_id == current_user.id)
    )
    prefs = result.scalar_one_or_none()

    if not prefs:
        prefs = UserPreference(
            user_id=current_user.id,
            preferred_email=current_user.email,
            alert_tier="standard",
        )
        db.add(prefs)

    # Update only fields that were provided
    update_data = request.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(prefs, field, value)

    await db.commit()
    await db.refresh(prefs)

    return {
        "message": "Preferences updated",
        "preferred_email": prefs.preferred_email,
        "whatsapp_number": prefs.whatsapp_number,
        "firm_name": prefs.firm_name,
        "ca_name": prefs.ca_name,
        "icai_membership_number": prefs.icai_membership_number,
        "firm_address": prefs.firm_address,
        "firm_phone": prefs.firm_phone,
        "firm_email": prefs.firm_email,
    }
