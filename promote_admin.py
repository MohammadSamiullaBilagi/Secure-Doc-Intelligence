"""One-time script to promote a user to admin by email.

Usage:
    python promote_admin.py your-email@example.com
"""
import asyncio
import sys

from sqlalchemy import select, update
from db.database import AsyncSessionLocal
# Import all models so SQLAlchemy resolves relationships
from db.models import core, billing, clients, calendar, notices, references, feedback  # noqa: F401
from db.models.core import User


async def promote(email: str):
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user:
            print(f"No user found with email: {email}")
            return
        if user.is_admin:
            print(f"{email} is already an admin.")
            return
        await db.execute(
            update(User).where(User.id == user.id).values(is_admin=True)
        )
        await db.commit()
        print(f"Promoted {email} to admin successfully.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python promote_admin.py <email>")
        sys.exit(1)
    asyncio.run(promote(sys.argv[1]))
