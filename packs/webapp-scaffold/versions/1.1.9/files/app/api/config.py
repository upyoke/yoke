"""{{project_display_name}} API configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    secret_key: str = "dev-secret-change-me"
    admin_password: str = ""
    data_dir: str = ""
    cors_origins: str = "http://localhost:{{web_port}}"
    host: str = "0.0.0.0"
    port: int = int("{{api_port}}")
    db_path: str = ""

    model_config = {"env_prefix": "APP_"}


def get_settings() -> Settings:
    return Settings()
