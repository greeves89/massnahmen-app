from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Maßnahmen-Auswertung"
    secret_key: str = "change-me-in-production-please-32-chars-min"
    database_url: str = "sqlite+aiosqlite:////data/massnahmen.db"

    initial_admin_email: str = "admin@example.com"
    initial_admin_password: str = "changeme"
    initial_admin_name: str = "Admin"

    session_cookie_name: str = "massnahmen_session"
    session_max_age_seconds: int = 60 * 60 * 24 * 14


settings = Settings()
