import time

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.routes import require, router
from app.config import Settings
from app.security.auth import DevAuthenticator, Principal
from app.security.rbac import Rbac
from app.security.secrets import KeyVaultSecretProvider, SecretError, is_reference, resolve_secrets
from app.workflow.service import EngagementService, Forbidden

MATRIX = {"a": ["*"], "b": ["Partner"], "c": ["Admin", "Auditor"], "d": []}
P = lambda *roles: Principal("u", "U", tuple(roles))


# ---- RBAC ----------------------------------------------------------------------------------------------------------
def test_wildcard_means_any_signed_in_user_even_with_no_roles():
    assert Rbac(MATRIX).allows(P(), "a")


def test_a_role_in_the_list_grants_the_permission_and_others_do_not():
    r = Rbac(MATRIX)
    assert r.allows(P("Partner"), "b") and not r.allows(P("Analyst"), "b") and not r.allows(P(), "b")
    assert r.allows(P("Auditor"), "c") and r.allows(P("Admin", "Analyst"), "c")


def test_default_deny_for_unknown_and_empty_permissions():
    r = Rbac(MATRIX)
    assert not r.allows(P("Partner", "Admin"), "no-such-permission")  # not in the matrix: nobody, not even admins
    assert not r.allows(P("Partner"), "d")


def test_overrides_replace_a_permission_and_none_leaves_it_alone():
    r = Rbac.from_policy({"x": ["Partner"], "y": ["Admin"]}, {"x": ["Director"], "y": None})
    assert r.roles_for("x") == ["Director"] and r.roles_for("y") == ["Admin"]
    assert Rbac.from_policy(None).matrix == {}


def test_permissions_of_and_describe():
    r = Rbac(MATRIX)
    assert r.permissions_of(P("Partner")) == ["a", "b"] and r.permissions_of(P()) == ["a"]
    assert r.describe("a") == "any signed-in user" and r.describe("c") == "one of: Admin, Auditor" and r.describe("zzz") == "nobody"


def test_the_shipped_policy_gives_the_expected_roles():
    svc = EngagementService(Settings(llm_provider="stub", database_url="sqlite:///:memory:"))
    r = svc.rbac
    assert r.roles_for("engagement:approve") == ["Partner"]
    assert r.allows(P("Admin"), "governance:view") and r.allows(P("Auditor"), "governance:view")
    assert not r.allows(P("Analyst"), "governance:view") and not r.allows(P("Partner"), "governance:view")
    assert r.allows(P(), "engagement:create") and r.allows(P(), "metrics:view")


def test_the_environment_can_override_who_approves_and_the_service_obeys():
    svc = EngagementService(Settings(llm_provider="stub", database_url="sqlite:///:memory:", approver_role="Director"))
    wid = svc.start(business_problem="Should we expand?", industry="Retail")["workflow_id"]
    with pytest.raises(Forbidden, match="Director"):
        svc.approve(wid, "approve", approver=P("Partner"))  # the policy default no longer applies
    assert svc.approve(wid, "approve", approver=P("Director"))["status"] == "completed"


def test_the_require_dependency_enforces_a_permission_with_a_helpful_403():
    svc = EngagementService(Settings(llm_provider="stub", database_url="sqlite:///:memory:"))
    app = FastAPI()
    app.include_router(router)
    app.state.service, app.state.authenticator = svc, DevAuthenticator()

    governance_only = require("governance:view")

    @app.get("/only-governance")
    def only(p: Principal = Depends(governance_only)):
        return {"ok": p.user_id}

    c = TestClient(app)
    denied = c.get("/only-governance", headers={"X-Dev-User": "ann", "X-Dev-Roles": "Analyst"})
    assert denied.status_code == 403 and "governance:view" in denied.json()["detail"] and "Admin, Auditor" in denied.json()["detail"]
    assert c.get("/only-governance", headers={"X-Dev-User": "ada", "X-Dev-Roles": "Admin"}).json() == {"ok": "ada"}
    assert c.get("/me", headers={"X-Dev-User": "ada", "X-Dev-Roles": "Admin"}).json()["permissions"].count("governance:view") == 1


# ---- secrets ---------------------------------------------------------------------------------------------------------------
class FakeSecret:
    def __init__(self, value):
        self.value = value


class FakeVault:
    def __init__(self, secrets, fail=None):
        self.secrets, self.fail, self.reads = secrets, fail, []

    def get_secret(self, name):
        self.reads.append(name)
        if self.fail:
            raise self.fail
        return FakeSecret(self.secrets.get(name))


def settings(**over):
    return Settings(llm_provider="stub", database_url="sqlite:///:memory:", **over)


def test_references_are_recognised():
    assert is_reference("keyvault:openai-key") and not is_reference("sk-123") and not is_reference("")


def test_a_reference_is_replaced_by_the_secret_from_the_vault():
    vault = KeyVaultSecretProvider("https://v.vault.azure.net", client=FakeVault({"aoai-key": "REALKEY123"}))
    out = resolve_secrets(settings(azure_openai_api_key="keyvault:aoai-key"), vault)
    assert out.azure_openai_api_key == "REALKEY123" and out.llm_provider == "stub"


def test_plain_values_and_unrelated_fields_are_left_alone_and_the_vault_is_not_called():
    client = FakeVault({})
    vault = KeyVaultSecretProvider("https://v", client=client)
    s = settings(azure_openai_api_key="literal-key")
    assert resolve_secrets(s, vault) is s and client.reads == []


def test_several_secrets_resolve_independently():
    vault = KeyVaultSecretProvider("https://v", client=FakeVault({"k": "KEY", "ai": "InstrumentationKey=x"}))
    out = resolve_secrets(settings(azure_openai_api_key="keyvault:k", applicationinsights_connection_string="keyvault:ai"), vault)
    assert (out.azure_openai_api_key, out.applicationinsights_connection_string) == ("KEY", "InstrumentationKey=x")


def test_a_reference_without_a_vault_stops_start_up_instead_of_being_used_as_a_key():
    with pytest.raises(SecretError, match="KEY_VAULT_URL is not set"):
        resolve_secrets(settings(azure_openai_api_key="keyvault:aoai-key"), None)
    with pytest.raises(SecretError, match="no secret name"):
        resolve_secrets(settings(azure_openai_api_key="keyvault:"), KeyVaultSecretProvider("https://v", client=FakeVault({})))


def test_a_missing_or_empty_secret_fails_fast_and_never_echoes_a_value():
    vault = KeyVaultSecretProvider("https://v", client=FakeVault({"empty": ""}))
    with pytest.raises(SecretError, match="empty"):
        vault.get("empty")
    boom = KeyVaultSecretProvider("https://v", client=FakeVault({}, fail=PermissionError("secret=TOPSECRET denied")))
    with pytest.raises(SecretError) as e:
        boom.get("aoai-key")
    assert "aoai-key" in str(e.value) and "PermissionError" in str(e.value) and "TOPSECRET" not in str(e.value)


def test_secrets_are_cached_for_a_while_then_refetched():
    now = [0.0]
    client = FakeVault({"k": "V1"})
    vault = KeyVaultSecretProvider("https://v", client=client, cache_ttl_sec=60, clock=lambda: now[0])
    assert vault.get("k") == "V1" and vault.get("k") == "V1" and client.reads == ["k"]
    client.secrets["k"] = "V2"  # rotated in the vault
    now[0] = 61
    assert vault.get("k") == "V2" and client.reads == ["k", "k"]


def test_settings_never_print_their_secrets():
    s = Settings(llm_provider="stub", azure_openai_api_key="SUPERSECRETKEY",
                 applicationinsights_connection_string="InstrumentationKey=abc",
                 database_url="postgresql://user:hunter2@db/x")
    text = repr(s) + str(s)
    for leaked in ("SUPERSECRETKEY", "InstrumentationKey=abc", "hunter2"):
        assert leaked not in text
    assert "azure_openai_api_key='***'" in repr(s)


def test_the_real_client_is_only_built_when_needed():
    vault = KeyVaultSecretProvider("https://v.vault.azure.net")
    assert vault._client is None  # nothing contacted at construction
    time.sleep(0)
