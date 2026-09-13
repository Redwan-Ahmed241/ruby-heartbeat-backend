'''Application configuration settings.'''
from typing import List
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Smart Blood Donation Management System (SBDMS)"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"

    DATABASE_URL: str = (
        "postgresql+psycopg2://postgres.fgvdkpuvdedenwmdjhym:keukonokajkorena@aws-0-ap-south-1.pooler.supabase.com:6543/postgres"
    )

    # JWT Settings
    JWT_SECRET: str = "supersecretjwtkey_for_sbdms_production_ready_2026_blood_hub"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7


    # CORS Settings
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:5173",
        "https://ruby-heartbeat-backend.vercel.app",
        "http://127.0.0.1:8000",

    ]
    CORS_ALLOW_ORIGIN_REGEX: str = r"https://.*\.vercel\.app"

    ENVIRONMENT: str = "development"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("DATABASE_URL", mode="after")
    @classmethod
    def assemble_db_url(cls, v: str) -> str:
        if not v:
            return v
        if v.startswith("postgres://"):
            v = "postgresql+psycopg2://" + v[11:]
        elif v.startswith("postgresql://"):
            v = "postgresql+psycopg2://" + v[13:]
        if "pooler.supabase.com" in v and "sslmode" not in v:
            sep = "&" if "?" in v else "?"
            v = f"{v}{sep}sslmode=require"
        return v


settings = Settings()
