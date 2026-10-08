import pytest

from app.observability.payload import cap_payload
from app.security.pii import scrub, scrub_text


@pytest.mark.parametrize("text,label", [
    ("Contact jane.doe@example.co.uk about it", "email"),
    ("call +44 7700 900123 today", "phone"),
    ("call (415) 555 0132 today", "phone"),
    ("card 4111 1111 1111 1111 on file", "card"),
    ("card 4111-1111-1111-1111", "card"),
    ("pay to GB82 WEST 1234 5698 7654 32", "iban"),
    ("key=sk_live_" + "a1b2c3d4e5f6g7h8i9j0", "secret"),
    ("password: hunter2", "secret"),
    ("Authorization: Bearer abcdefghijklmnop1234", "secret"),
    ("aws AKIAABCDEFGHIJKLMNOP", "secret"),
])
def test_detects_personal_data_and_secrets(text, label):
    out = scrub(text)
    assert out.counts[label] >= 1 and f"[{label}]" in out.value


@pytest.mark.parametrize("text", [
    "Budget under $10M and launch within 18 months",
    "revenue 65208896.37 at margin 0.304",
    "dated 2026-10-08 and 2026-10-08T07:57:32+00:00",
    "ids ret_11b376c7 doc_demo_1#0 wf_4ec8ac081c",
    "4111 1111 1111 1112",                      # fails the Luhn check: not a card
    "ROI is 16.3% with NPV 1,284,000 over 5 years",
    "sha 0123456789abcdef",                      # short hash, not an opaque secret
])
def test_leaves_business_figures_dates_and_ids_alone(text):
    assert scrub_text(text) == text


def test_scrubs_nested_structures_but_leaves_numbers():
    obj = {"rows": [{"owner": "ann@corp.com", "revenue": 12_000_000.5}], "n": 3, "ok": True, "none": None}
    out = scrub(obj)
    assert out.value == {"rows": [{"owner": "[email]", "revenue": 12_000_000.5}], "n": 3, "ok": True, "none": None}
    assert out.total == 1 and obj["rows"][0]["owner"] == "ann@corp.com"  # input is not mutated


def test_values_under_secret_looking_keys_are_replaced_whole():
    out = scrub({"api_key": "anything at all", "Authorization": "x", "name": "plain"})
    assert out.value == {"api_key": "[secret]", "Authorization": "[secret]", "name": "plain"}
    assert out.counts["secret"] == 2


def test_cap_payload_keeps_small_values_and_marks_large_ones():
    small = {"a": [1, 2, {"b": "c"}]}
    assert cap_payload(small) == small
    big = cap_payload({"rows": ["x" * 100] * 500}, max_chars=1000)
    assert big["_truncated"] is True and big["original_chars"] > 1000 and len(big["preview"]) == 1000


def test_cap_payload_never_raises_on_odd_values():
    class Odd:
        def __repr__(self):
            return "<odd>"
    assert cap_payload(Odd()) == "<odd>" or isinstance(cap_payload(Odd()), str)
    assert cap_payload({"d": {1, 2}}) is not None
