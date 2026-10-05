from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase


# PostgreSQL database configuration
DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/schedulix"


# Create database engine
engine = create_engine(
    DATABASE_URL,
    echo=True
)


# Create database session
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False
)


# Base class for all database models
class Base(DeclarativeBase):
    pass


# Dependency used by FastAPI routes
def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()