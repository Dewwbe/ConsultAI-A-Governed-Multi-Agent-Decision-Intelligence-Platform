from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import cors_origin_list, get_settings
from app.security.auth import build_authenticator
from app.security.secrets import KeyVaultSecretProvider, resolve_secrets
from app.workflow.service import EngagementService

settings = get_settings()
# `keyvault:<name>` in a secret setting is read from the vault named by KEY_VAULT_URL; an unresolved reference stops start-up.
settings = resolve_secrets(settings, KeyVaultSecretProvider(settings.key_vault_url) if settings.key_vault_url else None)
app = FastAPI(title="ConsultAI", version="0.4.0")
app.add_middleware(CORSMiddleware, allow_origins=cors_origin_list(settings),
                   allow_methods=["GET", "POST"],
                   allow_headers=["Authorization", "Content-Type", "Last-Event-ID", "X-Dev-User", "X-Dev-Roles"])
app.state.authenticator = build_authenticator(settings)  # refuses AUTH_MODE=dev outside ENVIRONMENT=dev
app.state.service = EngagementService(settings)
app.include_router(router)
