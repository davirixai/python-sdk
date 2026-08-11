"""Sir kodda emas, va u HECH QAYERDA ko'rinmaydi (repr, xato, log)."""

from __future__ import annotations

import logging

import contracts_support as cs
import httpx
import pytest

from conftest import API_KEY
from davirix import APIError, ConfigurationError, Davirix

CREATED = cs.execution_fixture("platform.execution.created.json")
ARGS = dict(agent_id="a", input={"text": "x"})


def test_kalit_env_dan_olinadi(monkeypatch):
    monkeypatch.setenv("DAVIRIX_API_KEY", "env-kalit")
    client = Davirix(tenant_id="t1", actor="service:x")
    assert client._api_key == "env-kalit"


def test_kalitsiz_mijoz_qurilmaydi(monkeypatch):
    """Jim autentifikatsiyasiz so'rov YO'Q — sozlama xatosi darhol ko'rinadi."""
    monkeypatch.delenv("DAVIRIX_API_KEY", raising=False)
    with pytest.raises(ConfigurationError) as info:
        Davirix(tenant_id="t1", actor="service:x")
    assert "DAVIRIX_API_KEY" in str(info.value)


def test_kalit_authorization_headerida_yuboriladi(make_client, recorder):
    make_client(lambda r: httpx.Response(201, json=CREATED)).start(**ARGS)
    (request,) = recorder.requests
    assert request.headers["authorization"] == f"Bearer {API_KEY}"
    assert request.headers["user-agent"].startswith("davirix-python/")


def test_repr_da_kalit_yoq(make_client):
    client = make_client(lambda r: httpx.Response(201, json=CREATED))
    assert API_KEY not in repr(client)
    assert "runtime.test" in repr(client)


def test_xato_matnida_kalit_yoq(make_client):
    """Xatoga so'rov obyekti biriktirilmaydi — header'lar u orqali sizmaydi."""
    handler = lambda r: httpx.Response(  # noqa: E731
        403, json={"detail": {"code": "service_token_tenant_mismatch", "message": "mos emas"}}
    )
    with pytest.raises(APIError) as info:
        make_client(handler).start(**ARGS)

    error = info.value
    for text in (str(error), repr(error), str(error.payload)):
        assert API_KEY not in text
    assert "Bearer" not in str(error)


def test_422_javobida_mijoz_matni_xatoga_tushmaydi(make_client):
    """FastAPI validatsiya tanasida `input` (PII) bo'lishi mumkin — u olinmaydi."""
    handler = lambda r: httpx.Response(  # noqa: E731
        422,
        json={
            "detail": [
                {
                    "loc": ["body", "input", "text"],
                    "msg": "String should have at least 1 character",
                    "input": "MIJOZNING MAXFIY MATNI",
                }
            ]
        },
    )
    with pytest.raises(APIError) as info:
        make_client(handler).start(**ARGS)

    assert "MIJOZNING MAXFIY MATNI" not in str(info.value)
    assert "body.input.text" in str(info.value)


def test_sdk_logga_kalit_yozmaydi(make_client, caplog):
    with caplog.at_level(logging.DEBUG, logger="davirix"):
        make_client(lambda r: httpx.Response(201, json=CREATED)).start(**ARGS)
    assert API_KEY not in caplog.text
