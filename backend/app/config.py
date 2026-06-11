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
    cookie_secure: bool = False  # set True when running behind HTTPS

    # AI Vision (Azure OpenAI for now — gpt-4.1 deployment)
    ai_enabled: bool = False
    azure_openai_endpoint: str = ""
    azure_openai_key: str = ""
    azure_openai_deployment: str = "gpt-4.1-mini"
    azure_openai_api_version: str = "2024-08-01-preview"


settings = Settings()
