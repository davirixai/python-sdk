"""QOIDA 4: retry FAQAT `retryable: true` da. Boshqa hech qachon.

Har test so'rovlar SONINI sanaydi — «qayta urinmadi» degan da'vo shu bilan
isbotlanadi.
"""

from __future__ import annotations

import contracts_support as cs
import httpx
import pytest

from davirix import (
    APIError,
    ConflictError,
    RateLimitError,
    ServiceUnavailableError,
    TransportError,
    UpstreamError,
    ValidationError,
    is_retryable,
)

CREATED = cs.execution_fixture("platform.execution.created.json")
ARGS = dict(agent_id="a", input={"text": "x"})


def _responses(*responses: httpx.Response):
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        return queue.pop(0) if queue else httpx.Response(500, json={"detail": "ortiqcha so'rov"})

    return handler


# ── qayta urinilmaydigan holatlar (asosiy himoya) ───────────────────────


def test_retryable_false_qayta_urinilmaydi(make_client, recorder):
    """MEZON 6: `retryable: false` — QAYTA URINMAYDI (bitta so'rov)."""
    handler = _responses(
        httpx.Response(502, json={"detail": {"code": "inference_error", "message": "gateway", "retryable": False}}),
        httpx.Response(201, json=CREATED),  # bunga yetib borilsa — test yiqiladi
    )
    with pytest.raises(UpstreamError) as info:
        make_client(handler).start(**ARGS)

    assert len(recorder.requests) == 1
    assert recorder.sleeps == []
    assert info.value.retryable is False
    assert info.value.status_code == 502


def test_retryable_maydonsiz_javob_qayta_urinilmaydi(make_client, recorder):
    """503 `retryable` bermadi — «ehtimol vaqtinchalikdir» TAXMIN QILINMAYDI."""
    handler = _responses(
        httpx.Response(503, json={"detail": {"code": "execution_store_unavailable", "message": "registr"}}),
        httpx.Response(201, json=CREATED),
    )
    with pytest.raises(ServiceUnavailableError):
        make_client(handler).start(**ARGS)
    assert len(recorder.requests) == 1


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (409, ConflictError),
        (422, ValidationError),
        (500, APIError),
    ],
)
def test_terminal_statuslar_qayta_urinilmaydi(make_client, recorder, status, expected):
    handler = _responses(
        httpx.Response(status, json={"detail": {"code": "x", "message": "y"}}),
        httpx.Response(201, json=CREATED),
    )
    with pytest.raises(expected) as info:
        make_client(handler).start(**ARGS)
    assert len(recorder.requests) == 1
    assert info.value.retryable is False


def test_tarmoq_uzilishi_qayta_urinilmaydi(make_client, recorder):
    """Javob KELMADI: POST server tomonida bajarilgan BO'LISHI MUMKIN.

    SDK taxmin qilmaydi. Mijoz qo'lda qayta chaqirsa xavfsiz — kalit
    deterministik (test_idempotency.py).
    """

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("ulanish uzildi", request=request)

    with pytest.raises(TransportError) as info:
        make_client(handler).start(**ARGS)

    assert len(recorder.requests) == 1
    assert info.value.retryable is False


# ── qayta urinish RUXSAT etilgan yagona yo'l ────────────────────────────


def test_429_qayta_urinadi_va_retry_after_hurmat_qilinadi(make_client, recorder):
    handler = _responses(
        httpx.Response(
            429,
            json={"detail": {"code": "observer_rate_limited", "message": "sekin", "retry_after_s": 1.5}},
            headers={"Retry-After": "2"},
        ),
        httpx.Response(201, json=CREATED),
    )
    execution = make_client(handler).start(**ARGS)

    assert execution.status == "created"
    assert len(recorder.requests) == 2
    assert recorder.sleeps == [1.5]  # server aytgan qiymat, taxmin emas


def test_502_retryable_true_qayta_urinadi(make_client, recorder):
    handler = _responses(
        httpx.Response(502, json={"detail": {"code": "inference_unavailable", "message": "502", "retryable": True}}),
        httpx.Response(201, json=CREATED),
    )
    make_client(handler).start(**ARGS)
    assert len(recorder.requests) == 2


def test_retry_budjeti_cheklangan(make_client, recorder):
    handler = _responses(*[httpx.Response(429, json={"detail": {"retry_after_s": 0.1}})] * 10)
    with pytest.raises(RateLimitError):
        make_client(handler, max_retries=2).start(**ARGS)
    assert len(recorder.requests) == 3  # 1 asosiy + 2 qayta urinish


def test_juda_uzoq_retry_after_kutilmaydi(make_client, recorder):
    """Server 10 daqiqa desa SDK erta urinib «hurmat qildim» demaydi — yiqiladi."""
    handler = _responses(httpx.Response(429, json={"detail": {"retry_after_s": 600}}))
    with pytest.raises(RateLimitError):
        make_client(handler, max_retry_wait_s=30).start(**ARGS)
    assert len(recorder.requests) == 1
    assert recorder.sleeps == []


# ── qaror nuqtasining o'zi ──────────────────────────────────────────────


@pytest.mark.parametrize("value", [1, "true", [1], object()])
def test_is_retryable_faqat_haqiqiy_true(value):
    """«Truthy» yetarli emas — AYNAN `True` kerak."""

    class Fake:
        retryable = value

    assert is_retryable(Fake()) is False


def test_is_retryable_notanish_xatoda_false():
    assert is_retryable(ValueError("begona xato")) is False
