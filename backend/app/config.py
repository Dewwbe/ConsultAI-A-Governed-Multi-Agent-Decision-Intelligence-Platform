from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: str = "stub"  # stub | azure_openai
    environment: str = "dev"
    database_url: str = "sqlite:///./consultai.db"  # postgresql://user:pw@host:5432/db in production

    # Authentication. `dev` trusts X-Dev-User/X-Dev-Roles headers and is refused outside ENVIRONMENT=dev.
    auth_mode: str = "dev"  # dev | entra
    entra_tenant_id: str = ""
    entra_client_id: str = ""  # expected token audience (the API's application ID)
    entra_audience: str = ""   # optional override, e.g. api://<client-id>
    # Optional overrides of policy.yaml `rbac` (leave unset to use the policy).
    approver_role: str | None = None
    # Roles that may see trace payloads (tool arguments/results, retrieved text) on confidential engagements.
    payload_roles: str | None = None  # comma-separated
    key_vault_url: str = ""  # a value like keyvault:<name> in a secret setting is read from this vault

    policy_file: str = str(Path(__file__).resolve().parents[2] / "policies" / "policy.yaml")

    max_tokens: int = 100_000
    max_cost_usd: float = 2.0
    max_duration_sec: int = 300
    max_tool_calls: int = 100
    # Optional overrides of policy.yaml `limits.engagements` (leave unset to use the policy).
    max_concurrent_runs: int | None = None
    max_queued_runs: int | None = None
    approval_risk_threshold: float = 0.7

    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""  # empty -> Microsoft Entra ID (DefaultAzureCredential)
    azure_openai_api_version: str = "2024-10-21"
    llm_timeout_sec: float = 30.0
    model_small: str = ""
    model_medium: str = ""
    model_reasoning: str = ""

    cors_origins: str = "http://localhost:5173,http://localhost:3000"  # comma-separated

    def __repr_args__(self):  # a stray print or log of the settings must not leak a key
        secret = {"azure_openai_api_key", "applicationinsights_connection_string", "database_url"}
        for key, value in super().__repr_args__():
            yield key, ("***" if key in secret and value else value)

    otel_exporter_otlp_endpoint: str = ""
    mlflow_tracking_uri: str = ""
    mlflow_experiment: str = "consultai"
    mlflow_artifact_location: str = ""  # a folder or blob URI; use a database tracking URI (sqlite:///, postgresql://)
    applicationinsights_connection_string: str = ""  # Azure Monitor / Application Insights
    otel_export_payloads: bool = False  # tool arguments/results and retrieved text stay out of exported spans


def cors_origin_list(settings: Settings) -> list[str]:
    return [o.strip() for o in settings.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
