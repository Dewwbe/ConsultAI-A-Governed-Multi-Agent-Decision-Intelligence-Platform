"""Authentication. Two modes, selected by AUTH_MODE:

* `entra`: validates Microsoft Entra ID access tokens (RS256 via the tenant's JWKS; issuer,
  audience, tenant, expiry and signature are all enforced). App roles come from the `roles` claim.
* `dev`: trusts `X-Dev-User` / `X-Dev-Roles` headers so the UI can be built before a tenant
  exists. Refused at startup unless ENVIRONMENT=dev, so it can never run in production.

Authorisation (who may approve) is enforced server-side in the service; hiding buttons in the UI
is a convenience only.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import jwt
from jwt import PyJWKClient


@dataclass(frozen=True)
class Principal:
    user_id: str
    name: str
    roles: tuple[str, ...] = field(default_factory=tuple)

    def has_role(self, role: str) -> bool:
        return role in self.roles


class AuthError(Exception):
    """Missing or invalid credentials (HTTP 401)."""


class Authenticator(Protocol):
    def authenticate(self, headers: Mapping[str, str]) -> Principal: ...


class DevAuthenticator:
    def authenticate(self, headers: Mapping[str, str]) -> Principal:
        user = headers.get("x-dev-user", "dev-user").strip() or "dev-user"
        roles = tuple(r.strip() for r in headers.get("x-dev-roles", "").split(",") if r.strip())
        return Principal(user, user, roles)


class EntraAuthenticator:
    def __init__(self, tenant_id: str, audience: str | list[str], jwks_client: Any = None,
                 leeway_sec: int = 30):
        self.tenant_id = tenant_id
        self.audience = audience
        self.issuers = [f"https://login.microsoftonline.com/{tenant_id}/v2.0",
                        f"https://sts.windows.net/{tenant_id}/"]  # v2 and v1 token formats
        self.leeway = leeway_sec
        self.jwks = jwks_client or PyJWKClient(
            f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys", cache_keys=True)

    def authenticate(self, headers: Mapping[str, str]) -> Principal:
        auth = headers.get("authorization", "")
        scheme, _, token = auth.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise AuthError("missing bearer token")
        try:
            key = self.jwks.get_signing_key_from_jwt(token.strip()).key
            claims = jwt.decode(token.strip(), key, algorithms=["RS256"], audience=self.audience,
                                issuer=self.issuers, leeway=self.leeway,
                                options={"require": ["exp", "iss", "aud"]})
        except jwt.PyJWTError as exc:
            raise AuthError(f"invalid token: {type(exc).__name__}") from exc
        if claims.get("tid") not in (None, self.tenant_id):
            raise AuthError("token issued for a different tenant")
        user_id = claims.get("oid") or claims.get("sub")
        if not user_id:
            raise AuthError("token has no subject")
        roles = claims.get("roles") or []
        if isinstance(roles, str):
            roles = [roles]
        name = claims.get("name") or claims.get("preferred_username") or user_id
        return Principal(str(user_id), str(name), tuple(roles))


def build_authenticator(settings: Any) -> Authenticator:
    if settings.auth_mode == "dev":
        if settings.environment != "dev":
            raise RuntimeError("AUTH_MODE=dev is only permitted when ENVIRONMENT=dev")
        return DevAuthenticator()
    if settings.auth_mode == "entra":
        if not settings.entra_tenant_id or not (settings.entra_audience or settings.entra_client_id):
            raise RuntimeError("AUTH_MODE=entra requires ENTRA_TENANT_ID and ENTRA_CLIENT_ID")
        audience = [a for a in (settings.entra_client_id, settings.entra_audience) if a]
        return EntraAuthenticator(settings.entra_tenant_id, audience)
    raise RuntimeError(f"unknown AUTH_MODE '{settings.auth_mode}'")
