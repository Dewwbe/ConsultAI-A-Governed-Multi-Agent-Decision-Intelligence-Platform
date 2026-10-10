from app.config import Settings
from app.demo_seed import SEED, seed_demo
from app.workflow.service import EngagementService


def service():
    return EngagementService(Settings(_env_file=None, llm_provider="stub", database_url="sqlite:///:memory:"))


def test_seeds_an_empty_database_with_engagements_in_each_state():
    svc = service()
    assert seed_demo(svc) == len(SEED)
    rows, total = svc.db.list_engagements(None, 50, 0)
    assert total == len(SEED)
    statuses = sorted(r["status"] for r in rows)
    assert statuses.count("awaiting_approval") == 2
    assert {"completed", "rejected"} <= set(statuses)


def test_does_not_seed_twice():
    svc = service()
    seed_demo(svc)
    assert seed_demo(svc) == 0
    assert svc.db.list_engagements(None, 50, 0)[1] == len(SEED)
