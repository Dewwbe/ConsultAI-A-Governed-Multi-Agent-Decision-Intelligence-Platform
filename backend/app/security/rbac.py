"""Role-based access control. The role-to-permission matrix lives in the versioned policy file, so who may do
what is reviewable, diffable and shown in the governance views, rather than scattered through the code.

Default deny: a permission that is not in the matrix is refused for everyone. `*` means any signed-in user.
The UI hides what a user cannot do as a convenience; this is the check that actually protects it.
"""
from __future__ import annotations

from .auth import Principal

ANY = "*"


class Rbac:
    def __init__(self, matrix: dict[str, list[str]]):
        self.matrix = {permission: list(roles) for permission, roles in matrix.items()}

    @classmethod
    def from_policy(cls, policy_rbac: dict[str, list[str]] | None, overrides: dict[str, list[str] | None] | None = None) -> Rbac:
        """`overrides` lets an operator replace one permission's roles from the environment (None = leave as is)."""
        matrix = {k: list(v) for k, v in (policy_rbac or {}).items()}
        for permission, roles in (overrides or {}).items():
            if roles:
                matrix[permission] = list(roles)
        return cls(matrix)

    def roles_for(self, permission: str) -> list[str]:
        return list(self.matrix.get(permission, []))

    def allows(self, principal: Principal, permission: str) -> bool:
        roles = self.matrix.get(permission)
        if roles is None:
            return False  # not in the matrix: nobody
        return ANY in roles or any(principal.has_role(r) for r in roles)

    def permissions_of(self, principal: Principal) -> list[str]:
        return sorted(p for p in self.matrix if self.allows(principal, p))

    def describe(self, permission: str) -> str:
        roles = self.roles_for(permission)
        return "any signed-in user" if ANY in roles else (f"one of: {', '.join(roles)}" if roles else "nobody")
