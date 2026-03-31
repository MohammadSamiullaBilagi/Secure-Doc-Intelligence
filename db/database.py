import asyncio
from datetime import datetime
from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, declared_attr, Mapped, mapped_column
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from db.config import settings

class Base(DeclarativeBase):
    """Base class for all SQLAlchemy 2.0 models."""
    
    @declared_attr.directive
    def __tablename__(cls) -> str:
        """Auto-generate table names from class names."""
        return cls.__name__.lower() + "s"

class TimestampMixin:
    """Provides created_at and updated_at columns for models."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow
    )
# Create the async engine
engine_args = {}
if settings.is_sqlite:
    engine_args["connect_args"] = {"check_same_thread": False}
else:
    # PostgreSQL connection pool settings
    engine_args["pool_size"] = 10
    engine_args["max_overflow"] = 20
    engine_args["pool_pre_ping"] = True
    engine_args["pool_recycle"] = 1800  # Recycle stale connections every 30 minutes

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    **engine_args
)

# Async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
    class_=AsyncSession
)

async def get_db():
    """FastAPI Dependency for getting async DB sessions."""
    async with AsyncSessionLocal() as session:
        yield session
