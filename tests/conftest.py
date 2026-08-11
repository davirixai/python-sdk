"""Umumiy test asboblari: soxta transport va kontrakt yo'llari."""

from __future__ import annotations

import json
from typing import Any, Callable, Sequence

import httpx
import pytest

from davirix import Davirix

API_KEY = "test-kalit-HECH-QAYERDA-KO'RINMASIN"


class Recorder:
    """So'rovlarni va uyqularni yozib boradi (haqiqiy kutish YO'Q)."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    @property
    def bodies(self) -> list[Any]:
        return [
            json.loads(r.content.decode("utf-8"))
            for r in self.requests
            if r.content
        ]


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def make_client(recorder: Recorder) -> Callable[..., Davirix]:
    """`handler(request) -> httpx.Response` bilan mijoz quradi (jonli server YO'Q)."""

    def factory(
        handler: Callable[[httpx.Request], httpx.Response] | Sequence[httpx.Response],
        **kwargs: Any,
    ) -> Davirix:
        if not callable(handler):
            queue = list(handler)

            def _sequence(request: httpx.Request) -> httpx.Response:
                recorder.requests.append(request)
                return queue.pop(0) if queue else httpx.Response(500)

            transport_handler = _sequence
        else:

            def _wrapped(request: httpx.Request) -> httpx.Response:
                recorder.requests.append(request)
                return handler(request)

            transport_handler = _wrapped

        kwargs.setdefault("tenant_id", "c601ce9c-0000-4000-8000-000000000001")
        kwargs.setdefault("actor", "service:sdk-test")
        return Davirix(
            api_key=API_KEY,
            base_url="https://runtime.test",
            transport=httpx.MockTransport(transport_handler),
            sleep=recorder.sleep,
            **kwargs,
        )

    return factory
