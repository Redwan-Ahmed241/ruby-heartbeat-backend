"""Database engine and session management configured for serverless/Vercel."""
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.core.config import settings

# Optimized pool settings for Supabase Transaction Pooler on port 6543
# pool_size=3, max_overflow=0, pool_recycle=300, pool_pre_ping=True
engine = create_engine(
    settings.DATABASE_URL,
    pool_size=3,
    max_overflow=0,
    pool_recycle=300,
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """FastAPI database session dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
