"""Fast connectivity check: one tiny structured call per model tier, printed as it happens.

    python backend/scripts/ping_llm.py

Takes a few seconds per tier. If this hangs or fails, the problem is credentials, endpoint,
deployment names or network, not the engagement pipeline.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from app.config import get_settings
from app.control_plane.llm import AzureOpenAIProvider, base_endpoint
from app.schemas.json_schema import STR, obj

SCHEMA = obj(answer=STR)


def main() -> int:
    s = get_settings()
    print(f"provider={s.llm_provider} endpoint={base_endpoint(s.azure_openai_endpoint) or '(not set)'} "
          f"key_chars={len(s.azure_openai_api_key)} api_version={s.azure_openai_api_version} "
          f"timeout={s.llm_timeout_sec}s", flush=True)
    provider = AzureOpenAIProvider(
        endpoint=s.azure_openai_endpoint, api_key=s.azure_openai_api_key,
        api_version=s.azure_openai_api_version, timeout_sec=s.llm_timeout_sec,
        deployments={"MODEL_SMALL": s.model_small, "MODEL_MEDIUM": s.model_medium,
                     "MODEL_REASONING": s.model_reasoning})
    failed = 0
    for key in ("MODEL_SMALL", "MODEL_MEDIUM", "MODEL_REASONING"):
        print(f"{key} ({provider.deployments.get(key) or 'NOT SET'}) ...", end=" ", flush=True)
        t = time.time()
        try:
            r = provider.complete_json(task="ping", system="Reply with JSON only.",
                                       prompt='Return {"answer": "pong"}.', schema=SCHEMA,
                                       context={}, model=key)
            print(f"ok {time.time() - t:.1f}s tokens={r.input_tokens}+{r.output_tokens} -> {r.content}")
        except Exception as exc:  # noqa: BLE001  report every failure kind
            failed += 1
            print(f"FAILED after {time.time() - t:.1f}s: {type(exc).__name__}: {str(exc)[:200]}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
