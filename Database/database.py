from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import settings
from Database.models import Base

engine_args = {}
if settings.is_sqlite:
    engine_args["connect_args"] = {"check_same_thread": False}

engine = create_engine(settings.sync_database_url, **engine_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    Base.metadata.create_all(bind=engine)
