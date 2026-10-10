"""Tests must be hermetic: never read backend/.env, call a real model, or touch a real Azure service."""
import os

os.environ["CONSULTAI_IGNORE_DOTENV"] = "1"

from app.config import Settings  # imported after the switch above, which it reads

# A developer's .env can hold live keys and point at real Azure services (search, Databricks, Cosmos...). Tests must
# never read it, so the file is switched off for every Settings object a test creates.
Settings.model_config["env_file"] = None

# Environment variables win over everything else. Pin the ones the app itself reads to their offline values, and drop
# any real-service variable that happens to be set in the shell. (Libraries such as the Azure exporter read some of
# these names themselves, so they are removed rather than set to empty.)
os.environ.update({
    "LLM_PROVIDER": "stub", "ENVIRONMENT": "dev", "AUTH_MODE": "dev", "DATABASE_URL": "sqlite:///:memory:",
    "RETRIEVER": "local", "DATA_SOURCE": "sqlite", "MEMORY_STORE": "memory", "DEMO_SEED": "false"})
for name in ("EMBEDDING_DEPLOYMENT", "AZURE_SEARCH_ENDPOINT", "DATABRICKS_HOST", "COSMOS_ENDPOINT", "KEY_VAULT_URL",
             "APPLICATIONINSIGHTS_CONNECTION_STRING", "OTEL_EXPORTER_OTLP_ENDPOINT", "MLFLOW_TRACKING_URI"):
    os.environ.pop(name, None)
