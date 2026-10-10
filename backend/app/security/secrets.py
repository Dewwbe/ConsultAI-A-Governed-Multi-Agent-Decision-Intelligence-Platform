"""Secrets from Azure Key Vault instead of environment files.

A setting that would hold a secret can instead say `keyvault:<secret-name>`; at start-up the value is fetched
from the vault (using the machine's managed identity, so there is no credential to store) and substituted.
If a reference cannot be resolved the service refuses to start, rather than sending the literal text
`keyvault:openai-key` to a provider as if it were a key. Secret values are never logged, and a failure names
the secret, never its value.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Protocol

REF_PREFIX = "keyvault:"
# Settings fields that may hold a secret, and so may be a keyvault: reference.
SECRET_FIELDS = ("azure_openai_api_key", "applicationinsights_connection_string", "database_url", "azure_search_api_key",
                 "databricks_token", "cosmos_key")


class SecretError(RuntimeError):
    """A secret could not be fetched. The message names the secret, never a value."""


class SecretProvider(Protocol):
    def get(self, name: str) -> str: ...


class KeyVaultSecretProvider:
    def __init__(self, vault_url: str, client: Any = None, cache_ttl_sec: float = 300.0,
                 clock: Any = time.monotonic):
        self.vault_url = vault_url
        self._client = client
        self._ttl, self._clock = cache_ttl_sec, clock
        self._cache: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()

    @property
    def client(self) -> Any:
        if self._client is None:
            from azure.identity import (
                DefaultAzureCredential,  # managed identity in Azure, az login locally
            )
            from azure.keyvault.secrets import SecretClient

            self._client = SecretClient(vault_url=self.vault_url, credential=DefaultAzureCredential())
        return self._client

    def get(self, name: str) -> str:
        with self._lock:
            hit = self._cache.get(name)
            if hit and self._clock() - hit[0] < self._ttl:
                return hit[1]
        try:
            value = self.client.get_secret(name).value
        except Exception as exc:
            raise SecretError(f"could not read secret '{name}' from {self.vault_url}: {type(exc).__name__}") from exc
        if not value:
            raise SecretError(f"secret '{name}' in {self.vault_url} is empty")
        with self._lock:
            self._cache[name] = (self._clock(), value)
        return value


def is_reference(value: str) -> bool:
    return value.startswith(REF_PREFIX)


def resolve_secrets(settings: Any, provider: SecretProvider | None) -> Any:
    """Return settings with every `keyvault:` reference replaced by its secret. Fails fast if one cannot be."""
    updates: dict[str, str] = {}
    for field in SECRET_FIELDS:
        value = getattr(settings, field, "")
        if isinstance(value, str) and is_reference(value):
            name = value[len(REF_PREFIX):].strip()
            if not name:
                raise SecretError(f"{field.upper()} is a keyvault: reference with no secret name")
            if provider is None:
                raise SecretError(f"{field.upper()} refers to Key Vault secret '{name}' but KEY_VAULT_URL is not set")
            updates[field] = provider.get(name)
    return settings.model_copy(update=updates) if updates else settings
