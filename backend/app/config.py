from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = "stub"  # stub | azure_openai
    environment: str = "dev"

    policy_file: str = str(Path(__file__).resolve().parents[2] / "policies" / "policy.yaml")

    max_tokens: int = 100_000
    max_cost_usd: float = 2.0
    max_duration_sec: int = 300
    max_tool_calls: int = 100
    approval_risk_threshold: float = 0.7

    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""  # empty -> Microsoft Entra ID (DefaultAzureCredential)
    azure_openai_api_version: str = "2024-10-21"
    llm_timeout_sec: float = 30.0
    model_small: str = ""
    model_medium: str = ""
    model_reasoning: str = ""

    cors_origins: str = "http://localhost:5173,http://localhost:3000"  # comma-separated

    otel_exporter_otlp_endpoint: str = ""
    mlflow_tracking_uri: str = ""


def cors_origin_list(settings: Settings) -> list[str]:
    return [o.strip() for o in settings.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
