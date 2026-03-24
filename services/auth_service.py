from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from db.config import settings

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain text password against the stored bcrypt hash."""
    pwd_bytes = plain_password.encode("utf-8")[:72]  # bcrypt 72-byte limit
    return bcrypt.checkpw(pwd_bytes, hashed_password.encode("utf-8"))

def get_password_hash(password: str) -> str:
    """Generates a bcrypt hash for the plain text password."""
    pwd_bytes = password.encode("utf-8")[:72]  # bcrypt 72-byte limit
    return bcrypt.hashpw(pwd_bytes, bcrypt.gensalt()).decode("utf-8")

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Creates a JWT access token encoding the provided data payloads."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt
