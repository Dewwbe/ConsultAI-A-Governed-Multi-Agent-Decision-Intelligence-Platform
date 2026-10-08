"""File-based prompt registry. Prompts live next to this module as `<name>.<version>.md`:

    <system prompt>
    ---USER---
    <user prompt, string.Template syntax: $variable>

The latest version of a name is the highest `vN`. Every LLM call records `name@version`
in its trace span, so any output can be tied back to the exact prompt that produced it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from string import Template

_DIR = Path(__file__).parent
_SEP = "---USER---"
_FILE = re.compile(r"^(?P<name>[a-z_]+)\.v(?P<version>\d+)\.md$")


@dataclass(frozen=True)
class PromptTemplate:
    name: str
    version: int
    system: str
    user: str

    @property
    def id(self) -> str:
        return f"{self.name}@v{self.version}"

    def render(self, **variables: object) -> tuple[str, str]:
        """Return (system, user). Missing variables raise KeyError rather than shipping `$x`."""
        values = {k: str(v) for k, v in variables.items()}
        return self.system, Template(self.user).substitute(values)


class PromptNotFound(KeyError):
    pass


@lru_cache
def _index() -> dict[str, dict[int, Path]]:
    found: dict[str, dict[int, Path]] = {}
    for path in _DIR.glob("*.md"):
        m = _FILE.match(path.name)
        if m:
            found.setdefault(m["name"], {})[int(m["version"])] = path
    return found


def get_prompt(name: str, version: int | None = None) -> PromptTemplate:
    versions = _index().get(name)
    if not versions:
        raise PromptNotFound(name)
    v = version if version is not None else max(versions)
    if v not in versions:
        raise PromptNotFound(f"{name}@v{v}")
    system, sep, user = versions[v].read_text(encoding="utf-8").partition(_SEP)
    if not sep:
        raise ValueError(f"{versions[v].name} is missing the {_SEP} separator")
    return PromptTemplate(name, v, system.strip(), user.strip())


def available() -> dict[str, list[int]]:
    return {n: sorted(v) for n, v in _index().items()}
