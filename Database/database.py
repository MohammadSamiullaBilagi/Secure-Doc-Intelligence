from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import settings
from Database.models import Base

# echo=False in prod to prevent log spam
engine = create_engine(
    settings.database_url, 
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)