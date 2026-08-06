from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
import os

# Calculate the path to the root Backend directory
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_PATH = os.path.join(ROOT_DIR, ".env")

class Settings(BaseSettings):
    PROJECT_NAME: str = "ExamBuddy API"
    VERSION: str = "1.1.0"
    API_V1_STR: str = "/api/v1"

    # Supabase / DB
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"

    # Cloudinary
    CLOUDINARY_CLOUD_NAME: str = ""
    CLOUDINARY_API_KEY: str = ""
    CLOUDINARY_API_SECRET: str = ""

    # Gemini
    GEMINI_API_KEY: str = ""

    # Security
    SECRET_KEY: str = "SUPER_SECRET_KEY"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440

    model_config = SettingsConfigDict(env_file=ENV_PATH, env_file_encoding="utf-8", case_sensitive=True, extra="ignore")

settings = Settings()
