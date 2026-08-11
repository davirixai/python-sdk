"""Ijro natijasi va AMAL holati — SDK'ning markaziy qarori shu faylda.

# `completed` ≠ «bajarildi»

`status: completed` — **model javob berdi** degani. Amal (SMS ketdimi, karta
yangilandimi) bajarildimi — bu FAQAT `operations[]` da ko'rinadi. Konnektor
timeout bersa amal Ledger'da `UNKNOWN` bo'lib qoladi, xato esa model'ga
`tool_result` bo'lib qaytadi va model BARIBIR chiroyli javob yozishi mumkin:

    status = "completed"          ← model javob berdi
    operations[0].status = "UNKNOWN"   ← SMS ketdimi — NOMA'LUM

Shu bois bu modul quyidagilarni MAJBURLAYDI:

1. `bool(execution)` — **TypeError**. «if natija: bajarildi deb yozish» — eng
   qisqa yolg'on yo'li. U yopiq.
2. `execution.success` / `.ok` / `.done` / `.completed` kabi nomlar —
   **AttributeError** aniq ko'rsatma bilan. Bunday xossa YO'Q, chunki
   bunday YAGONA javob ham yo'q.
3. `verified` — FAIL-CLOSED: server `operations[]` bermasa ham, holat
   tanish bo'lmasa ham **False**. «Bilmadim» hech qachon «ha» ga aylanmaydi.
4. Tasdiqlanmagan amal bilan tugagan ijro kod tomonidan HECH QACHON
   o'qilmasa — obyekt yo'q qilinayotganda `davirix` logger'iga WARNING
   yoziladi (asyncio'ning «Task exception was never retrieved» naqshi).

# `UNKNOWN` — istisno EMAS

Bu modul `UNKNOWN` uchun istisno KO'TARMAYDI. Sabab quruq amaliy: istisno
ko'rilgan joyda mijoz `except: retry` yozadi, va qayta yuborilgan amal
DUBLIKAT effekt beradi (ikkinchi SMS, ikkinchi to'lov). `UNKNOWN` dan yagona
chiqish yo'li — reconciliation, mijozning qayta urinishi EMAS.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

from davirix.errors import UnverifiedError

logger = logging.getLogger("davirix")

_warn_unread = True


def set_unverified_warning(enabled: bool) -> None:
    """Tasdiqlanmagan amal «o'qilmay qoldi» ogohlantirishini yoqish/o'chirish."""
    global _warn_unread
    _warn_unread = bool(enabled)


class ExecutionStatus(str, Enum):
    """`contracts/platform/execution/v1/execution.schema.json#/$defs/status`."""

    CREATED = "created"
    VALIDATING = "validating"
    RESOLVING_CONTEXT = "resolving_context"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_FOR_TOOL = "waiting_for_tool"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    VALIDATING_OUTPUT = "validating_output"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


#: Terminal holatlar — bundan keyin ijro o'zgarmaydi.
TERMINAL_STATUSES = frozenset(
    {
        ExecutionStatus.COMPLETED.value,
        ExecutionStatus.FAILED.value,
        ExecutionStatus.CANCELLED.value,
        ExecutionStatus.EXPIRED.value,
    }
)


class OperationStatus(str, Enum):
    """`execution.schema.json#/$defs/executionOperation/status`.

    ⚡ `VERIFIED` — manbadan tasdiqlangan, «bajarildi» ma'nosini beradigan
    YAGONA qiymat. `ACKNOWLEDGED` — konnektor javob berdi (TRANSPORT), natija
    tasdiqlanmagan. `UNKNOWN` — natija noma'lum: qayta yuborish TAQIQ.
    """

    PREPARED = "PREPARED"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    VERIFIED = "VERIFIED"
    UNKNOWN = "UNKNOWN"
    RECONCILING = "RECONCILING"
    FAILED = "FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    CANCELLED = "CANCELLED"


_KNOWN_OPERATION_STATUSES = frozenset(s.value for s in OperationStatus)

#: Natijasi NOMA'LUM: qayta yuborish TAQIQ (yagona chiqish — reconciliation).
_RESEND_FORBIDDEN = frozenset(
    {OperationStatus.UNKNOWN.value, OperationStatus.RECONCILING.value}
)

#: Amal tugadi, lekin effekt YO'Q (yoki qaytarilgan).
_NO_EFFECT = frozenset(
    {OperationStatus.FAILED.value, OperationStatus.CANCELLED.value}
)


@dataclass(frozen=True)
class Operation:
    """Bitta BIZNES amali va uning tasdiqlangan taqdiri."""

    operation_id: str
    capability_id: str
    #: XOM qiymat (kontraktdagidek). Yangi server yangi holat qo'shsa u
    #: YO'QOLMAYDI — enum'ga majburan sig'dirilmaydi.
    status: str
    resource_ref: str | None = None
    verification_method: str | None = None
    verification_evidence: str | None = None
    terminal_reason: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "Operation":
        return cls(
            operation_id=str(data.get("operation_id", "")),
            capability_id=str(data.get("capability_id", "")),
            status=str(data.get("status", "")),
            resource_ref=data.get("resource_ref"),
            verification_method=data.get("verification_method"),
            verification_evidence=data.get("verification_evidence"),
            terminal_reason=data.get("terminal_reason"),
        )

    @property
    def verified(self) -> bool:
        """FAQAT manbadan tasdiqlangan amal uchun True (fail-closed).

        `verification_method: NONE` — kontrakt bo'yicha «tasdiqlanmagan»;
        bunday amal `VERIFIED` deb kelsa ham tasdiqlangan deb ATALMAYDI
        (ziddiyatda ishonchsiz tomon tanlanadi).
        """
        if self.status != OperationStatus.VERIFIED.value:
            return False
        return self.verification_method != "NONE"

    @property
    def known_status(self) -> bool:
        """Holat kontraktdagi ro'yxatdami. False — yangi/noto'g'ri server qiymati."""
        return self.status in _KNOWN_OPERATION_STATUSES

    @property
    def resend_forbidden(self) -> bool:
        """Bu amalni qayta yuborish TAQIQMI (fail-closed).

        `UNKNOWN`/`RECONCILING` — taqiq. Tanish bo'lmagan holat ham taqiq:
        ma'nosi noma'lum qiymatni «xavfsiz» deb hisoblash — taxmin.
        """
        if not self.known_status:
            return True
        return self.status in _RESEND_FORBIDDEN

    @property
    def effect_unknown(self) -> bool:
        """Effekt bo'ldimi — noma'lum (ha ham, yo'q ham deyish YOLG'ON)."""
        if not self.known_status:
            return True
        if self.status in _RESEND_FORBIDDEN:
            return True
        # PREPARED/SENT/ACKNOWLEDGED/MANUAL_REVIEW: hali tasdiqlanmagan.
        return self.status not in _NO_EFFECT and not self.verified


class Verdict(str, Enum):
    """Ijro amallari haqidagi YAGONA hukm (`verified` shundan chiqadi)."""

    #: Barcha yozuv amallari manbadan tasdiqlangan.
    VERIFIED = "verified"
    #: `operations: []` — bu ijroda yozuv amali BO'LMAGAN (faqat javob).
    NO_ACTIONS = "no_actions"
    #: Kamida bitta amal NOMA'LUM — qayta yuborish TAQIQ.
    UNKNOWN = "unknown"
    #: Kamida bitta amal FAILED/CANCELLED (effekt yo'q).
    FAILED_ACTION = "failed_action"
    #: Amal(lar) hali yo'lda: PREPARED/SENT/ACKNOWLEDGED/MANUAL_REVIEW.
    PENDING_ACTION = "pending_action"
    #: Server `operations[]` BERMADI — bilib bo'lmaydi (fail-closed).
    UNREPORTED = "unreported"
    #: Ijro `completed` emas (running/failed/cancelled/expired/waiting...).
    NOT_COMPLETED = "not_completed"


#: `verified is True` beradigan YAGONA ikki hukm.
_VERIFIED_VERDICTS = frozenset({Verdict.VERIFIED, Verdict.NO_ACTIONS})

#: Xato nomlar: mijoz shularni yozganda JIM `None` emas, ko'rsatma oladi.
_FORBIDDEN_ATTRS = {
    "success": "muvaffaqiyat",
    "succeeded": "muvaffaqiyat",
    "ok": "muvaffaqiyat",
    "is_ok": "muvaffaqiyat",
    "done": "bajarildi",
    "is_done": "bajarildi",
    "completed": "bajarildi",
    "is_completed": "bajarildi",
    "executed": "bajarildi",
    "applied": "bajarildi",
    "delivered": "yetkazildi",
}


@dataclass(frozen=True)
class OperationsCoverage:
    """`operations[]` ga ISHONISH mumkinmi (kontrakt: `operationsCoverage`).

    Uch holat farqlanadi va SDK uchalasini ham ARALASHTIRMAYDI:
      * massiv bor           → bilamiz;
      * bo'sh massiv         → yozuv amali bo'lmagan;
      * `complete: false`    → BILMAYMIZ (sabab `degraded_reasons` da).
    """

    complete: bool
    degraded_reasons: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "OperationsCoverage":
        reasons = data.get("degraded_reasons")
        return cls(
            # Fail-closed: AYNAN `true` bo'lsagina to'liq deb hisoblanadi.
            complete=data.get("complete") is True,
            degraded_reasons=(
                tuple(str(r) for r in reasons) if isinstance(reasons, list) else ()
            ),
        )


@dataclass(frozen=True)
class ExecutionError:
    """`status=failed` dagi xato konverti."""

    code: str
    message: str | None = None
    #: Server aytgan qayta urinish huquqi. SDK ijroni O'ZI qayta yurgizmaydi:
    #: yangi ijro — YANGI effekt. Qarorni mijoz qabul qiladi.
    retryable: bool | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ExecutionError":
        return cls(
            code=str(data.get("code", "")),
            message=data.get("message"),
            retryable=data.get("retryable"),
        )


@dataclass(frozen=True)
class WaitingFor:
    """`status=waiting_for_approval` — qaysi interrupt kutilmoqda."""

    kind: str
    interrupt_id: str
    expires_at: str | None = None
    payload: Mapping[str, Any] | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "WaitingFor":
        return cls(
            kind=str(data.get("kind", "")),
            interrupt_id=str(data.get("interrupt_id", "")),
            expires_at=data.get("expires_at"),
            payload=data.get("payload"),
        )


class Execution:
    """Bitta ijro — `contracts/platform/execution/v1/execution.schema.json`.

    Xom konvert `raw` da TO'LIQ saqlanadi: yangi server yangi maydon qo'shsa
    SDK uni YO'QOTMAYDI (oldinga muvofiqlik), lekin uni tushungan deb ham
    ko'rsatmaydi.
    """

    __slots__ = (
        "raw",
        "_operations",
        "_operations_reported",
        "_coverage",
        "_inspected",
    )

    def __init__(self, payload: Mapping[str, Any]) -> None:
        if not isinstance(payload, Mapping):
            raise TypeError(f"Execution konverti obyekt bo'lishi kerak, {type(payload).__name__} keldi")
        self.raw: Mapping[str, Any] = dict(payload)
        ops = payload.get("operations")
        coverage = payload.get("operations_coverage")
        self._coverage: OperationsCoverage | None = (
            OperationsCoverage.from_dict(coverage) if isinstance(coverage, Mapping) else None
        )
        # ⚠ «maydon yo'q» va «bo'sh massiv» BIR XIL EMAS:
        #   []      → yozuv amali bo'lmagan (server aytdi);
        #   yo'q    → server aytmadi → bilib bo'lmaydi → fail-closed.
        # Qoplama `complete: false` desa massiv KELGAN bo'lsa ham ishonilmaydi
        # (kontrakt bunday juftlikni taqiqlaydi; server buzsa — biz emas, u
        # yolg'on aytgan bo'ladi va biz uni takrorlamaymiz).
        self._operations_reported = isinstance(ops, list) and (
            self._coverage is None or self._coverage.complete
        )
        self._operations: tuple[Operation, ...] = (
            tuple(Operation.from_dict(o) for o in ops if isinstance(o, Mapping))
            if isinstance(ops, list)
            else ()
        )
        self._inspected = False

    # ── identifikatorlar va holat ───────────────────────────────────────

    @property
    def execution_id(self) -> str:
        return str(self.raw.get("execution_id", ""))

    @property
    def tenant_id(self) -> str:
        return str(self.raw.get("tenant_id", ""))

    @property
    def thread_id(self) -> str:
        return str(self.raw.get("thread_id", ""))

    @property
    def idempotency_key(self) -> str | None:
        return self.raw.get("idempotency_key")

    @property
    def status(self) -> str:
        """XOM holat satri (`"completed"`, `"running"`, ...).

        ⚠ `completed` — MODEL javob berdi degani. Amal bajarildimi —
        `verified` va `operations` da.
        """
        return str(self.raw.get("status", ""))

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES

    @property
    def is_settled(self) -> bool:
        """Kutishning ma'nosi qolmadi: terminal YOKI odam qarorini kutmoqda."""
        return self.is_terminal or self.status == ExecutionStatus.WAITING_FOR_APPROVAL.value

    @property
    def text(self) -> str | None:
        """Model javobi. ⚠ Bu — MATN, amal isboti EMAS."""
        result = self.raw.get("result")
        if not isinstance(result, Mapping):
            return None
        output = result.get("output")
        if not isinstance(output, Mapping):
            return None
        value = output.get("text")
        return value if isinstance(value, str) else None

    @property
    def result(self) -> Mapping[str, Any] | None:
        value = self.raw.get("result")
        return value if isinstance(value, Mapping) else None

    @property
    def error(self) -> ExecutionError | None:
        value = self.raw.get("error")
        return ExecutionError.from_dict(value) if isinstance(value, Mapping) else None

    @property
    def waiting_for(self) -> WaitingFor | None:
        value = self.raw.get("waiting_for")
        return WaitingFor.from_dict(value) if isinstance(value, Mapping) else None

    # ── amallar (bu yerda «bajarildimi» hal bo'ladi) ────────────────────

    @property
    def coverage(self) -> OperationsCoverage | None:
        """Amal qoplamasi (server bermasa None — eski/kontraktdan orqada server)."""
        self._inspected = True
        return self._coverage

    @property
    def operations_reported(self) -> bool:
        """`operations[]` ga ishonish mumkinmi (berilgan VA qoplama to'liq)."""
        return self._operations_reported

    @property
    def operations(self) -> tuple[Operation, ...]:
        self._inspected = True
        return self._operations

    @property
    def verdict(self) -> Verdict:
        """Amallar bo'yicha yagona hukm. Eng XAVFLI holat ustun keladi."""
        self._inspected = True
        if self.status != ExecutionStatus.COMPLETED.value:
            return Verdict.NOT_COMPLETED
        if not self._operations_reported:
            return Verdict.UNREPORTED
        if not self._operations:
            return Verdict.NO_ACTIONS
        # Tartib ATAYLAB: noma'lum — eng xavflisi, u yashirilmaydi.
        if any(op.resend_forbidden for op in self._operations):
            return Verdict.UNKNOWN
        if all(op.verified for op in self._operations):
            return Verdict.VERIFIED
        if any(op.status in _NO_EFFECT for op in self._operations):
            return Verdict.FAILED_ACTION
        return Verdict.PENDING_ACTION

    @property
    def verified(self) -> bool:
        """BARCHA yozuv amallari manbadan tasdiqlanganmi.

        FAIL-CLOSED. False bo'lishining sabablari turlicha (`verdict`):
        noma'lum, kutilmoqda, muvaffaqiyatsiz, YOKI server umuman aytmagan.
        «Bilmadim» hech qachon True bermaydi.
        """
        return self.verdict in _VERIFIED_VERDICTS

    @property
    def unverified_operations(self) -> tuple[Operation, ...]:
        """Tasdiqlanmagan amallar (bo'sh — hammasi tasdiqlangan yoki amal yo'q)."""
        self._inspected = True
        return tuple(op for op in self._operations if not op.verified)

    @property
    def unknown_operations(self) -> tuple[Operation, ...]:
        """Natijasi NOMA'LUM amallar. ⚠ Ularni QAYTA YUBORISH TAQIQ."""
        self._inspected = True
        return tuple(op for op in self._operations if op.resend_forbidden)

    def require_verified(self) -> "Execution":
        """«Bu yerda tasdiqlangan amal SHART» — mijoz OSHKORA aytadi.

        Tasdiqlanmagan bo'lsa `UnverifiedError` (retryable=False, terminal).
        SDK buni O'ZI hech qachon chaqirmaydi.
        """
        self._inspected = True
        if self.verified:
            return self
        raise UnverifiedError(
            f"ijro {self.execution_id or '<id yo‘q>'}: status={self.status!r}, "
            f"hukm={self.verdict.value!r} — amal TASDIQLANMAGAN. "
            "Qayta yuborish TAQIQ (reconciliation aniqlaydi).",
            execution=self,
            operations=self.unverified_operations,
        )

    def require_completed(self) -> "Execution":
        """Ijro `completed` bo'lishini talab qiladi (amal holati HAQIDA EMAS)."""
        if self.status == ExecutionStatus.COMPLETED.value:
            return self
        raise UnverifiedError(
            f"ijro {self.execution_id or '<id yo‘q>'}: status={self.status!r} "
            "— `completed` emas",
            execution=self,
        )

    def explain(self) -> str:
        """Odam o'qiydigan bir qatorli xulosa (log va xabar uchun)."""
        self._inspected = True
        parts = [f"status={self.status}", f"verdict={self.verdict.value}"]
        if not self._operations_reported:
            reasons = self._coverage.degraded_reasons if self._coverage else ()
            parts.append(
                "operations=BERILMAGAN" + (f"({','.join(reasons)})" if reasons else "")
            )
        else:
            parts.append(
                "operations="
                + (
                    ",".join(f"{op.capability_id}:{op.status}" for op in self._operations)
                    or "yo'q"
                )
            )
        return " ".join(parts)

    # ── e'tiborsiz qoldirishga qarshi to'siqlar ─────────────────────────

    def __bool__(self) -> bool:
        raise TypeError(
            "Execution ni bool qilib bo'lmaydi. `if natija:` — «completed» ni "
            "«bajarildi» deb o'qishning eng qisqa yo'li. "
            "`execution.verified` (amal manbadan tasdiqlanganmi) yoki "
            "`execution.status` (ijro holati) dan foydalaning."
        )

    def __getattr__(self, name: str) -> Any:
        # Faqat NOTO'G'RI nomlar uchun: qolganlari odatdagi AttributeError.
        meaning = _FORBIDDEN_ATTRS.get(name)
        if meaning is None:
            raise AttributeError(
                f"{type(self).__name__!r} obyektida {name!r} xossasi yo'q"
            )
        raise AttributeError(
            f"`Execution.{name}` ATAYLAB yo'q: bitta «{meaning}» javobi mavjud emas. "
            "`status` — model javob berdimi; `verified` — amal manbadan "
            "tasdiqlanganmi; `verdict` — nega tasdiqlanmagani. "
            "Ikkalasi bir xil savol EMAS."
        )

    def __repr__(self) -> str:
        ops = (
            ",".join(op.status for op in self._operations)
            if self._operations_reported
            else "BERILMAGAN"
        )
        return (
            f"<Execution {self.execution_id or '?'} status={self.status!r} "
            f"operations=[{ops}]>"
        )

    def __del__(self) -> None:
        # asyncio'ning «Task exception was never retrieved» naqshi: jim
        # yo'qolgan xavf — ENG YOMON holat. Faqat HAQIQIY noaniqlikda
        # (server amal berdi, u tasdiqlanmagan, kod esa qaramadi).
        try:
            if not _warn_unread or self._inspected:
                return
            if self._coverage is not None and not self._coverage.complete:
                # OSHKORA degradatsiya: eski server emas, «bilmayman» signali.
                logger.warning(
                    "davirix: ijro %s `%s` bo'ldi, lekin amal holati NOMA'LUM "
                    "(qoplama to'liq emas: %s) va kod unga qaramadi. "
                    "`execution.coverage` / `.verified` ni tekshiring.",
                    self.execution_id or "?",
                    self.status,
                    ", ".join(self._coverage.degraded_reasons) or "sabab yo'q",
                )
                return
            if not self._operations_reported:
                return
            risky = [op for op in self._operations if not op.verified]
            if not risky:
                return
            logger.warning(
                "davirix: ijro %s `%s` bo'ldi, lekin %d amal TASDIQLANMAGAN (%s) "
                "va kod ularni o'qimadi. `execution.verified` / `.operations` "
                "ni tekshiring — `completed` «bajarildi» degani emas.",
                self.execution_id or "?",
                self.status,
                len(risky),
                ", ".join(f"{op.capability_id}={op.status}" for op in risky),
            )
        except Exception:  # pragma: no cover - __del__ hech qachon ko'tarmaydi
            pass


def parse_executions(payloads: Iterable[Mapping[str, Any]]) -> list[Execution]:
    """Ro'yxat konvertlarini `Execution` ga o'giradi (yordamchi)."""
    return [Execution(p) for p in payloads]


__all__ = [
    "Execution",
    "ExecutionError",
    "ExecutionStatus",
    "Operation",
    "OperationStatus",
    "OperationsCoverage",
    "TERMINAL_STATUSES",
    "Verdict",
    "WaitingFor",
    "parse_executions",
    "set_unverified_warning",
]
