"""QOIDA 3: `idempotency_key` avtomatik va BARQAROR.

Kalit bo'lmasa tarmoq uzilishida mijoz qayta chaqiradi va dublikat himoyasi
NIYAT darajasida ishlamaydi: server ikkinchi ijroni yaratadi, ikkinchi SMS
ketadi.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap

import contracts_support as cs
import httpx
import pytest

from davirix import Davirix, InvalidRequestError, derive_idempotency_key

_ARGS = dict(agent_id="mkbank-support", input={"text": "Mijozga SMS yubor"})


def _echo(status: int = 201):
    payload = cs.execution_fixture("platform.execution.created.json")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return handler


def test_kalit_har_sorovda_yuboriladi(make_client, recorder):
    make_client(_echo()).start(**_ARGS)

    (body,) = recorder.bodies
    assert body["idempotency_key"].startswith("dx1-")
    assert 1 <= len(body["idempotency_key"]) <= 128  # kontrakt chegarasi


def test_ayni_argumentlar_ayni_kalit(make_client, recorder):
    """MEZON 7: ayni argumentlar → ayni kalit (ikki MUSTAQIL mijozda ham)."""
    make_client(_echo()).start(**_ARGS)
    make_client(_echo()).start(**_ARGS)

    first, second = [b["idempotency_key"] for b in recorder.bodies]
    assert first == second


def test_boshqa_argument_boshqa_kalit(make_client, recorder):
    make_client(_echo()).start(**_ARGS)
    make_client(_echo()).start(agent_id="mkbank-support", input={"text": "Boshqa niyat"})
    make_client(_echo()).start(agent_id="boshqa-agent", input=_ARGS["input"])

    keys = [b["idempotency_key"] for b in recorder.bodies]
    assert len(set(keys)) == 3


def test_argument_tartibi_kalitni_ozgartirmaydi(make_client, recorder):
    make_client(_echo()).start(agent_id="a", input={"text": "x"}, thread_id="thr_1")
    make_client(_echo()).start(thread_id="thr_1", input={"text": "x"}, agent_id="a")

    first, second = [b["idempotency_key"] for b in recorder.bodies]
    assert first == second


def test_mijoz_bergan_kalit_ozgarmaydi(make_client, recorder):
    make_client(_echo()).start(**_ARGS, key="buyurtma-42")

    (body,) = recorder.bodies
    assert body["idempotency_key"] == "buyurtma-42"


def test_juda_uzun_kalit_rad_etiladi(make_client):
    with pytest.raises(InvalidRequestError):
        make_client(_echo()).start(**_ARGS, key="x" * 129)


def test_kalit_jarayondan_qatiy_nazar_barqaror():
    """PYTHONHASHSEED o'zgarsa ham kalit AYNI — boshqa mashinada ham shu."""
    program = textwrap.dedent(
        """
        import json, sys
        from davirix import derive_idempotency_key
        body = {
            "tenant_id": "t1",
            "actor": {"type": "service", "id": "billing"},
            "input": {"type": "message", "text": "Mijozga SMS yubor"},
            "agent_id": "mkbank-support",
            "variables": {"amount": "5000", "currency": "uzs"},
        }
        print(derive_idempotency_key(body))
        """
    )
    keys = set()
    for seed in ("0", "1", "12345"):
        out = subprocess.run(
            [sys.executable, "-c", program],
            capture_output=True,
            text=True,
            check=True,
            env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": seed, "PYTHONPATH": ":".join(sys.path)},
        )
        keys.add(out.stdout.strip())
    assert len(keys) == 1, keys


def test_kalit_tanadan_chiqadi_kalitning_ozisiz():
    """Kalit tanadan chiqariladi; tanaga qo'shilgach u O'ZINI o'zgartirmaydi."""
    body = {"tenant_id": "t1", "input": {"type": "message", "text": "x"}}
    key = derive_idempotency_key(body)
    assert derive_idempotency_key(dict(body)) == key
    assert "idempotency_key" not in body


def test_sorov_tanasi_kontrakt_sxemasiga_mos(make_client, recorder):
    """SDK yuborayotgan tana `execution-create-request` sxemasidan CHIQMAYDI."""
    make_client(_echo()).start(
        **_ARGS,
        workspace_id="ws_1",
        thread_id="thr_1",
        context_refs=[{"type": "deal", "id": "deal_1"}],
        variables={"amount": "5000"},
        channel="telegram",
        origin="direct",
        execution_mode="active",
        memory_consent=False,
        user_id="user_1",
    )

    (body,) = recorder.bodies
    errors = sorted(
        cs.validator(f"{cs.EXECUTION_V1}/execution-create-request.schema.json").iter_errors(body),
        key=lambda e: e.path,
    )
    assert not errors, json.dumps([e.message for e in errors], ensure_ascii=False)


def test_graph_version_graph_idsiz_tarmoqqa_chiqmaydi(make_client, recorder):
    """Kontrakt buzilishi TARMOQQA chiqmaydi — 422 ni SDK keltirib chiqarmaydi."""
    with pytest.raises(InvalidRequestError):
        make_client(_echo()).start(graph_version="1.1.0", input={"text": "x"})
    assert recorder.requests == []
