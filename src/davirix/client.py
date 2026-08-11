"""HTTP mijoz — auth, idempotentlik, retry.

Uchta qat'iy qoida shu faylda kod bilan qulflangan:

1. **`idempotency_key` HAR DOIM yuboriladi va DETERMINISTIK.** Mijoz kalit
   bermasa u so'rov tanasining KANONIK shaklidan chiqariladi
   (`_canonical.py` — platformaning `semantic_key`/`action_hash` bilan AYNI
   qoidalar). Ayni argumentlar → ayni kalit → server ikkinchi ijro
   YARATMAYDI. Shu bois tarmoq uzilganda mijozning qo'lda qayta chaqirishi
   XAVFSIZ.
2. **Retry FAQAT `retryable is True` da.** Yagona qaror nuqtasi —
   `errors.is_retryable`. Javob KELMAGAN xato (`TransportError`) qayta
   urinilmaydi: SDK «ehtimol yetib bormagandir» deb TAXMIN qilmaydi.
3. **Sir logga tushmaydi.** `api_key` faqat `Authorization` header'ida
   yashaydi; `repr()` da ham, xato matnida ham YO'Q (so'rov obyekti
   xatoga biriktirilmaydi).
"""

from __future__ import annotations

import os
import random
import time
from typing import Any, Callable, Mapping, Sequence

import httpx

from davirix._canonical import digest
from davirix.errors import (
    APIError,
    AuthError,
    ConfigurationError,
    ConflictError,
    ExecutionTimeout,
    InvalidRequestError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ServiceUnavailableError,
    TransportError,
    UpstreamError,
    ValidationError,
    is_retryable,
)
from davirix.result import Execution

__version_header__ = "davirix-python/0.1.0"

DEFAULT_BASE_URL = "https://api.davirix.com"
_EXECUTIONS = "/v1/executions"

#: Deterministik kalit prefiksi. Versiyalangan: kalit chiqarish qoidasi
#: kelajakda o'zgarsa `dx2-` bo'ladi va eski kalitlar bilan ARALASHMAYDI.
_KEY_PREFIX = "dx1-"

#: Kontrakt: `execution-create-request.schema.json` (`additionalProperties: false`).
#: Sxemada yo'q maydon YUBORILMAYDI — 422 ni SDK'ning o'zi keltirib chiqarmaydi.
_ALLOWED_BODY_FIELDS = frozenset(
    {
        "tenant_id",
        "workspace_id",
        "actor",
        "agent_id",
        "graph_id",
        "graph_version",
        "agent_template",
        "input",
        "context_refs",
        "idempotency_key",
        "thread_id",
        "model_profile_id",
        "user_id",
        "memory_consent",
        "execution_mode",
        "origin",
        "channel",
        "variables",
    }
)


def derive_idempotency_key(body: Mapping[str, Any]) -> str:
    """So'rov tanasidan DETERMINISTIK idempotentlik kaliti.

    Ayni niyat (ayni tana) → ayni kalit, jarayon va mashinadan qat'i nazar
    (`PYTHONHASHSEED` ta'sir qilmaydi: kalitlar saralanadi).
    """
    return _KEY_PREFIX + digest(dict(body))


class Davirix:
    """Davirix ijro sirti mijozi (`/v1/executions`).

    api_key: `DAVIRIX_API_KEY` env'dan ham olinadi. ⛔ Kodga yozilmaydi.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        tenant_id: str | None = None,
        actor: Mapping[str, str] | str | None = None,
        timeout: float = 30.0,
        max_retries: int = 2,
        max_retry_wait_s: float = 30.0,
        # Tayyor `httpx.Client` QABUL QILINMAYDI: begona mijozga auth
        # header'ini jim qo'shish (yoki qo'shmaslik) — ikkalasi ham yomon.
        # Moslashtirish uchun `transport` yetadi (proxy, mock, retry-siz pool).
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        user_agent: str = __version_header__,
    ) -> None:
        key = api_key if api_key is not None else os.environ.get("DAVIRIX_API_KEY")
        if not key:
            raise ConfigurationError(
                "API kaliti yo'q: `Davirix(api_key=...)` yoki `DAVIRIX_API_KEY` env. "
                "Sirni kodga yozish TAQIQ."
            )
        self._api_key = key
        self._base_url = (base_url or os.environ.get("DAVIRIX_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self._tenant_id = tenant_id or os.environ.get("DAVIRIX_TENANT_ID") or None
        self._actor = _normalize_actor(actor) if actor is not None else None
        self._max_retries = max(0, int(max_retries))
        self._max_retry_wait_s = float(max_retry_wait_s)
        self._sleep = sleep
        self._http = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            transport=transport,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": user_agent,
            },
        )

    # ── ijro sirti ──────────────────────────────────────────────────────

    def start(
        self,
        *,
        input: Mapping[str, Any] | str,
        agent_id: str | None = None,
        graph_id: str | None = None,
        graph_version: str | None = None,
        agent_template: str | None = None,
        key: str | None = None,
        tenant_id: str | None = None,
        actor: Mapping[str, str] | str | None = None,
        workspace_id: str | None = None,
        thread_id: str | None = None,
        context_refs: Sequence[Mapping[str, str]] | None = None,
        model_profile_id: str | None = None,
        user_id: str | None = None,
        memory_consent: bool | None = None,
        execution_mode: str | None = None,
        origin: str | None = None,
        channel: str | None = None,
        variables: Mapping[str, str] | None = None,
    ) -> Execution:
        """Ijro yaratadi va DARHOL qaytadi (kutmaydi).

        `key` berilmasa idempotentlik kaliti tanadan chiqariladi.
        """
        body = self._build_body(
            input=input,
            agent_id=agent_id,
            graph_id=graph_id,
            graph_version=graph_version,
            agent_template=agent_template,
            tenant_id=tenant_id,
            actor=actor,
            workspace_id=workspace_id,
            thread_id=thread_id,
            context_refs=context_refs,
            model_profile_id=model_profile_id,
            user_id=user_id,
            memory_consent=memory_consent,
            execution_mode=execution_mode,
            origin=origin,
            channel=channel,
            variables=variables,
        )
        body["idempotency_key"] = _validated_key(key) if key else derive_idempotency_key(body)
        response = self._request("POST", _EXECUTIONS, json=body)
        return Execution(response)

    def run(
        self,
        *,
        wait_timeout: float = 120.0,
        poll_interval: float = 0.25,
        **kwargs: Any,
    ) -> Execution:
        """Ijro yaratadi va u YAKUNLANGUNCHA kutadi.

        Qaytadi: terminal ijro (`completed`/`failed`/`cancelled`/`expired`)
        YOKI `waiting_for_approval` (odam qarorisiz davom etmaydi).

        ⚠ `completed` qaytishi «amal bajarildi» degani EMAS —
        `execution.verified` va `execution.operations` ni tekshiring.
        """
        execution = self.start(**kwargs)
        return self.wait(execution, wait_timeout=wait_timeout, poll_interval=poll_interval)

    def wait(
        self,
        execution: Execution | str,
        *,
        tenant_id: str | None = None,
        wait_timeout: float = 120.0,
        poll_interval: float = 0.25,
    ) -> Execution:
        """Ijro yakunlanguncha (yoki approval kutishiga tushguncha) so'raydi."""
        current = execution if isinstance(execution, Execution) else None
        execution_id = current.execution_id if current is not None else str(execution)
        tenant = tenant_id or (current.tenant_id if current is not None else None)
        if current is not None and current.is_settled:
            return current
        deadline = time.monotonic() + float(wait_timeout)
        interval = max(0.01, float(poll_interval))
        while True:
            current = self.get(execution_id, tenant_id=tenant)
            if current.is_settled:
                return current
            if time.monotonic() >= deadline:
                raise ExecutionTimeout(
                    f"ijro {execution_id} {wait_timeout}s ichida yakunlanmadi — u SERVERDA "
                    "davom etmoqda. `dx.get(execution_id)` bilan kuzatishda davom eting; "
                    "qayta `run()` — yangi effekt xavfi.",
                    execution_id=execution_id,
                    last=current,
                )
            self._sleep(min(interval, max(0.0, deadline - time.monotonic())))
            interval = min(interval * 1.6, 2.0)

    def get(self, execution_id: str, *, tenant_id: str | None = None) -> Execution:
        """Ijro holati. Begona tenant 404 oladi (mavjudlik ham ma'lumot)."""
        tenant = self._require_tenant(tenant_id)
        payload = self._request(
            "GET", f"{_EXECUTIONS}/{execution_id}", params={"tenant_id": tenant}
        )
        return Execution(payload)

    def cancel(self, execution_id: str, *, tenant_id: str | None = None) -> Execution:
        """Kooperativ bekor qilish: ishlayotgan qadam o'rtasidan UZILMAYDI."""
        tenant = self._require_tenant(tenant_id)
        payload = self._request(
            "POST",
            f"{_EXECUTIONS}/{execution_id}/cancel",
            json={"tenant_id": tenant},
        )
        return Execution(payload)

    # ── ichki ───────────────────────────────────────────────────────────

    def _build_body(
        self,
        *,
        input: Mapping[str, Any] | str,
        tenant_id: str | None,
        actor: Mapping[str, str] | str | None,
        graph_id: str | None,
        graph_version: str | None,
        context_refs: Sequence[Mapping[str, str]] | None,
        variables: Mapping[str, str] | None,
        **optional: Any,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "tenant_id": self._require_tenant(tenant_id),
            "actor": _normalize_actor(actor) if actor is not None else self._require_actor(),
            "input": _normalize_input(input),
        }
        if graph_version and not graph_id:
            # Kontrakt: `graph_id`siz `graph_version` — 422. Tarmoqqa chiqmasdan aytamiz.
            raise InvalidRequestError(
                "`graph_version` faqat `graph_id` bilan beriladi (kontrakt qoidasi)"
            )
        if graph_id:
            body["graph_id"] = graph_id
        if graph_version:
            body["graph_version"] = graph_version
        if context_refs is not None:
            body["context_refs"] = [dict(ref) for ref in context_refs]
        if variables is not None:
            body["variables"] = dict(variables)
        for name, value in optional.items():
            if value is None:
                continue
            if name not in _ALLOWED_BODY_FIELDS:  # pragma: no cover - dasturchi xatosi
                raise InvalidRequestError(f"kontraktda yo'q maydon: {name!r}")
            body[name] = value
        return body

    def _require_tenant(self, tenant_id: str | None) -> str:
        tenant = tenant_id or self._tenant_id
        if not tenant:
            raise InvalidRequestError(
                "`tenant_id` shart: `Davirix(tenant_id=...)` yoki chaqiruvda bering"
            )
        return tenant

    def _require_actor(self) -> dict[str, str]:
        if self._actor is None:
            raise InvalidRequestError(
                "`actor` shart: `Davirix(actor={'type': 'service', 'id': '...'})` "
                "yoki chaqiruvda bering (audit va approval-authz shunga tayanadi)"
            )
        return dict(self._actor)

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        attempt = 0
        while True:
            try:
                response = self._http.request(method, url, **kwargs)
            except httpx.HTTPError as exc:
                # Javob KELMADI. Qayta urinish YO'Q (qoida 2): POST server
                # tomonida bajarilgan bo'lishi mumkin. Kalit deterministik
                # bo'lgani uchun mijozning qo'lda qayta chaqirishi xavfsiz.
                raise TransportError(
                    f"{method} {url}: javob kelmadi ({type(exc).__name__}). "
                    "SDK avtomatik qayta urinmaydi — ijro server tomonida "
                    "boshlangan bo'lishi mumkin."
                ) from exc
            if response.is_success:
                return _json_body(response)
            error = _api_error(response)
            if attempt < self._max_retries and is_retryable(error):
                wait = _retry_wait(error, attempt)
                if wait <= self._max_retry_wait_s:
                    attempt += 1
                    self._sleep(wait)
                    continue
            raise error

    # ── resurs boshqaruvi ───────────────────────────────────────────────

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "Davirix":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    def __repr__(self) -> str:
        # ⛔ `api_key` bu yerda YO'Q va bo'lmaydi.
        return f"<Davirix base_url={self._base_url!r} tenant_id={self._tenant_id!r}>"


# ── yordamchilar ────────────────────────────────────────────────────────


def _normalize_input(value: Mapping[str, Any] | str) -> dict[str, Any]:
    if isinstance(value, str):
        text = value
    elif isinstance(value, Mapping):
        if value.get("type") not in (None, "message"):
            raise InvalidRequestError(
                f"kirish turi {value.get('type')!r} qo'llanmaydi — kontraktda yagona tur: 'message'"
            )
        raw = value.get("text")
        if not isinstance(raw, str):
            raise InvalidRequestError("`input.text` satr bo'lishi shart")
        text = raw
    else:
        raise InvalidRequestError(
            f"`input` — satr yoki {{'text': ...}} bo'lishi kerak, {type(value).__name__} keldi"
        )
    if not text:
        raise InvalidRequestError("`input.text` bo'sh bo'lmasligi kerak")
    if len(text) > 32768:
        raise InvalidRequestError("`input.text` 32768 belgidan uzun (kontrakt chegarasi)")
    return {"type": "message", "text": text}


def _normalize_actor(actor: Mapping[str, str] | str) -> dict[str, str]:
    if isinstance(actor, str):
        kind, _, ident = actor.partition(":")
        if not ident:
            raise InvalidRequestError("`actor` satri 'type:id' shaklida bo'lishi kerak")
        data = {"type": kind, "id": ident}
    elif isinstance(actor, Mapping):
        data = {"type": str(actor.get("type", "")), "id": str(actor.get("id", ""))}
    else:
        raise InvalidRequestError(f"`actor` noto'g'ri tip: {type(actor).__name__}")
    if data["type"] not in {"user", "agent", "service", "system"}:
        raise InvalidRequestError(
            f"`actor.type` {data['type']!r} — kontraktda: user|agent|service|system"
        )
    if not data["id"]:
        raise InvalidRequestError("`actor.id` bo'sh bo'lmasligi kerak")
    return data


def _validated_key(key: str) -> str:
    if not isinstance(key, str) or not key:
        raise InvalidRequestError("`key` bo'sh bo'lmagan satr bo'lishi kerak")
    if len(key) > 128:
        raise InvalidRequestError("`key` 128 belgidan uzun (kontrakt chegarasi)")
    return key


def _json_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise APIError(
            "server JSON qaytarmadi",
            status_code=response.status_code,
            retryable=False,
        ) from exc


def _api_error(response: httpx.Response) -> APIError:
    """HTTP javobdan typed xato. `retryable` FAQAT server aytganda True."""
    status = response.status_code
    code: str | None = None
    message: str = ""
    retryable = False
    retry_after: float | None = None
    payload: Any = None
    try:
        payload = response.json()
    except ValueError:
        payload = None
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, Mapping):
        code = detail.get("code")
        message = str(detail.get("message") or "")
        retryable = detail.get("retryable") is True
        value = detail.get("retry_after_s")
        retry_after = float(value) if isinstance(value, (int, float)) else None
    elif isinstance(detail, str):
        message = detail
    elif isinstance(detail, list):
        # FastAPI validatsiya xatosi: FAQAT joy va sabab olinadi — `input`
        # maydonida mijoz matni (PII) bo'lishi mumkin, u xato matniga tushmaydi.
        message = "; ".join(
            f"{'.'.join(str(p) for p in item.get('loc', []))}: {item.get('msg', '')}"
            for item in detail
            if isinstance(item, Mapping)
        )[:512]
    if not message:
        message = f"HTTP {status}"
    header_retry_after = response.headers.get("Retry-After")
    if retry_after is None and header_retry_after:
        try:
            retry_after = float(header_retry_after)
        except ValueError:
            retry_after = None

    kwargs: dict[str, Any] = {
        "status_code": status,
        "code": code,
        "payload": payload,
        "retry_after_s": retry_after,
    }
    if status in (401, 403):
        return AuthError(message, retryable=False, **kwargs)
    if status == 404:
        return NotFoundError(message, retryable=False, **kwargs)
    if status == 409:
        return ConflictError(message, retryable=False, **kwargs)
    if status == 422:
        return ValidationError(message, retryable=False, **kwargs)
    if status == 429:
        return RateLimitError(message, **kwargs)
    if status == 502:
        # Faqat server OSHKORA `retryable: true` desa.
        return UpstreamError(message, retryable=retryable, **kwargs)
    if status == 503:
        return ServiceUnavailableError(message, retryable=retryable, **kwargs)
    if status >= 500:
        return ServerError(message, retryable=retryable, **kwargs)
    return APIError(message, retryable=False, **kwargs)


def _retry_wait(error: APIError, attempt: int) -> float:
    """Kutish: server aytgan `Retry-After` ustun, aks holda eksponensial + jitter."""
    if error.retry_after_s is not None:
        return max(0.0, float(error.retry_after_s))
    return min(8.0, 0.5 * (2**attempt)) * (0.75 + random.random() * 0.5)


__all__ = ["Davirix", "DEFAULT_BASE_URL", "derive_idempotency_key"]
