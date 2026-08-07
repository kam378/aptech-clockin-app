from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://clockin_user:change-this-local-password@localhost:5432/clockin"
    app_env: str = "development"
    
    jwt_secret_key: str = "dev-only-secret-change-me"
    jwt_access_token_expire_minutes: int = 60 * 12

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
