from pydantic import BaseModel, EmailStr, Field
from uuid import UUID
from datetime import datetime
from typing import Optional

class UserCreate(BaseModel):
    """Payload for registering a new user."""
    email: EmailStr
    password: str

class UserResponse(BaseModel):
    """Payload for returning user data (never includes password)."""
    id: UUID
    email: EmailStr
    is_active: bool
    created_at: datetime
    
    class Config:
        from_attributes = True

class Token(BaseModel):
    """OAuth2 JWT Token Response"""
    access_token: str
    token_type: str

class TokenData(BaseModel):
    """Data decoded from the JWT token"""
    user_id: Optional[str] = None


class LoginRequest(BaseModel):
    """JSON-based login payload (used by frontend apps like Lovable)."""
    email: EmailStr
    password: str


class UpdatePreferencesRequest(BaseModel):
    """Payload for updating user preferences including CA branding."""
    preferred_email: Optional[str] = None
    whatsapp_number: Optional[str] = None
    firm_name: Optional[str] = None
    ca_name: Optional[str] = None
    icai_membership_number: Optional[str] = None
    firm_address: Optional[str] = None
    firm_phone: Optional[str] = None
    firm_email: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    """Payload for changing password (authenticated user)."""
    current_password: str = Field(..., min_length=8)
    new_password: str = Field(..., min_length=8)


class ForgotPasswordRequest(BaseModel):
    """Payload for requesting a password reset email."""
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Payload for resetting password with a token."""
    token: str
    new_password: str = Field(..., min_length=8)
