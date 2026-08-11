"""Kanonikalizatsiya — UMUMIY kontrakt fixture'i bilan qulflangan.

`idempotency_key` shu qoidalardan chiqadi. Agar SDK'ning kanonik shakli
platformanikidan ajralib ketsa, «bir niyat» ning ta'rifi ikki xil bo'lardi:
mijoz bir xil deb hisoblagan chaqiruv server uchun BOSHQA niyat bo'lib,
dublikat effekt yaratardi. Shu bois SDK Go va Python etalonlari bilan AYNI
fixture'ni yurgizadi: `contracts/execution/v1/fixtures/canonicalization.json`.
"""

from __future__ import annotations

import contracts_support as cs
import pytest

from davirix import canonical, digest

_CASES = cs.load_json(f"{cs.EXECUTION_LEDGER_V1}/fixtures/canonicalization.json")["cases"]


def test_fixture_bosh_emas():
    assert len(_CASES) >= 10, "kanonikalizatsiya fixture'i kutilganidan kichik"


@pytest.mark.parametrize("case", _CASES, ids=[c["name"] for c in _CASES])
def test_kanonik_shakl_kontraktdagidek(case: dict):
    assert canonical(case["params"]) == case["canonical"], case.get("why", "")
    assert digest(case["params"]) == case["digest"], case.get("why", "")


def test_ayni_daydjest_ayni_niyat():
    """Fixture'dagi juftliklar (`*_teskari`, `*_toza`) AYNI daydjest berishi shart."""
    by_digest: dict[str, set[str]] = {}
    for case in _CASES:
        by_digest.setdefault(digest(case["params"]), set()).add(case["name"])
    # Kamida bitta guruh 2+ case'ni birlashtiradi (aks holda fixture kuchsiz).
    assert any(len(names) > 1 for names in by_digest.values())
