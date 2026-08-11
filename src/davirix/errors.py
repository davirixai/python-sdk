"""Xatolar — `retryable` va `terminal` ATAYLAB ajratilgan.

QOIDA (buzilmaydi): SDK FAQAT `retryable is True` bo'lgan xatoni qayta
urinadi. Boshqa hech qachon. Shu bois:

* bazaviy `DavirixError.retryable` — **False** (fail-closed): yangi xato turi
  qo'shilsa u avtomatik «qayta urinsa bo'ladi» bo'lib qolmaydi;
* `retryable` FAQAT server OSHKORA aytganda True bo'ladi
  (429, yoki javob tanasida `retryable: true`);
* tarmoq uzilishi (javob KELMAGAN) — `TransportError`, `retryable=False`.
  Sabab: javobsiz POST server tomonida BAJARILGAN bo'lishi mumkin. SDK uni
  o'zi takrorlamaydi; mijoz o'zi qayta chaqirsa ham xavfsiz, chunki
  `idempotency_key` DETERMINISTIK (`client.py`) — server ayni niyatni
  ikkinchi ijro qilmaydi.

⚠ `UNKNOWN` amal holati bu yerda YO'Q va hech qachon bo'lmaydi. U — xato
emas, MA'LUMOT: «natija noma'lum». Uni istisno qilish mijozni
`except: retry` yozishga undardi va dublikat effekt yaratardi — platformaning
Ledger himoyasi aynan shu nuqtada bekor bo'lardi (`result.py` hujjati).
"""

from __future__ import annotations

from typing import Any


class DavirixError(Exception):
    """Barcha SDK xatolarining ildizi. Standart: qayta urinilmaydi."""

    #: Fail-closed: yangi xato turi qayta urinish huquqini MEROS OLMAYDI.
    retryable: bool = False

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = bool(retryable)


class InvalidRequestError(DavirixError, ValueError):
    """So'rov SDK'dan chiqmasdan TURIB yaroqsiz (kontrakt qoidasi buzilgan).

    `ValueError` dan ham meros oladi: bu — chaqiruvchi kodidagi xato,
    tarmoq hodisasi emas.
    """


class ConfigurationError(DavirixError):
    """Sozlama yetishmaydi (masalan API kaliti berilmagan)."""


class TransportError(DavirixError):
    """Javob KELMADI (ulanish/timeout). HECH QACHON avtomatik qayta urinilmaydi."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class APIError(DavirixError):
    """Server javob berdi, lekin muvaffaqiyatsiz status bilan."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        code: str | None = None,
        retryable: bool = False,
        retry_after_s: float | None = None,
        payload: Any = None,
    ) -> None:
        super().__init__(message, retryable=retryable)
        self.status_code = status_code
        self.code = code
        self.retry_after_s = retry_after_s
        #: Server tanasi (sir tutmaydi: SDK unga so'rov header'larini QO'SHMAYDI).
        self.payload = payload

    def __str__(self) -> str:  # pragma: no cover - trivial
        head = f"[{self.status_code}"
        if self.code:
            head += f" {self.code}"
        return f"{head}] {self.message}"


class AuthError(APIError):
    """401/403 — token yo'q, yaroqsiz yoki tenant mos emas. Qayta urinilmaydi."""


class NotFoundError(APIError):
    """404 — ijro yo'q yoki BOShQA tenant'niki (mavjudlikning o'zi ham ma'lumot)."""


class ConflictError(APIError):
    """409 — AYNI `idempotency_key`, BOSHQA tana.

    Bu yolg'on emas, HIMOYA: kalit boshqa niyat uchun ishlatilgan. Qayta
    urinish holatni o'zgartirmaydi — kalitni yoki tanani to'g'rilash kerak.
    """


class ValidationError(APIError):
    """422 — so'rov kontraktga mos emas. Ayni tana bilan qayta urinish befoyda."""


class RateLimitError(APIError):
    """429 — server OSHKORA «keyinroq urin» dedi. Yagona doimiy retryable holat."""

    def __init__(self, message: str, **kw: Any) -> None:
        kw["retryable"] = True
        super().__init__(message, **kw)


class UpstreamError(APIError):
    """502 — quyi tizim (masalan inference gateway). `retryable` TANADAN olinadi."""


class ServiceUnavailableError(APIError):
    """503 — registr/ombor yetib bo'lmadi (fail-closed).

    Tana `retryable` bermasa SDK QAYTA URINMAYDI: «ehtimol vaqtinchalikdir»
    degan taxmin qoidani buzadi.
    """


class ServerError(APIError):
    """5xx (boshqalari). Standart: qayta urinilmaydi."""


class ExecutionTimeout(DavirixError):
    """SDK kutish budjeti tugadi — ijro esa SERVERDA DAVOM ETMOQDA.

    ⚠ Bu «bajarilmadi» degani EMAS. Qayta `run()` chaqirish YANGI niyat
    yaratmaydi (kalit deterministik), lekin to'g'ri yo'l — `dx.get(id)`
    bilan o'sha ijroni kuzatishda davom etish.
    """

    def __init__(self, message: str, *, execution_id: str, last: Any = None) -> None:
        super().__init__(message, retryable=False)
        self.execution_id = execution_id
        #: Oxirgi ko'rilgan `Execution` (holatni o'qish uchun).
        self.last = last


class UnverifiedError(DavirixError):
    """FAQAT `Execution.require_verified()` chaqirilganda ko'tariladi.

    SDK buni O'ZI hech qachon ko'tarmaydi — mijoz «bu yerda tasdiqlangan
    amal SHART» deb OSHKORA aytganda ko'tariladi.

    `retryable` — o'qish uchungina xossa va HAR DOIM False: tasdiqlanmagan
    (ayniqsa `UNKNOWN`) amalni qayta yuborish TAQIQ.
    """

    def __init__(self, message: str, *, execution: Any = None, operations: Any = ()) -> None:
        super().__init__(message, retryable=False)
        self.execution = execution
        self.operations = tuple(operations)

    @property  # type: ignore[override]
    def retryable(self) -> bool:  # noqa: D102 - hujjat yuqorida
        return False

    @retryable.setter
    def retryable(self, value: bool) -> None:
        # Yozishga ruxsat bor (bazaviy `__init__` qo'yadi), lekin qiymat
        # E'TIBORGA OLINMAYDI: qayta yuborish taqiqi kod bilan qulflangan.
        if value:
            raise ValueError(
                "UnverifiedError qayta urinish uchun emas — tasdiqlanmagan amalni "
                "qayta yuborish TAQIQ (reconciliation aniqlaydi)"
            )


def is_retryable(exc: BaseException) -> bool:
    """Yagona qaror nuqtasi: `retryable` AYNAN `True` bo'lsagina."""
    return getattr(exc, "retryable", False) is True


__all__ = [
    "APIError",
    "AuthError",
    "ConfigurationError",
    "ConflictError",
    "DavirixError",
    "ExecutionTimeout",
    "InvalidRequestError",
    "NotFoundError",
    "RateLimitError",
    "ServerError",
    "ServiceUnavailableError",
    "TransportError",
    "UnverifiedError",
    "UpstreamError",
    "ValidationError",
    "is_retryable",
]
