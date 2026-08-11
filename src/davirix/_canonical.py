"""Kanonik shakl va deterministik daydjest.

Spetsifikatsiya: `contracts/execution/v1/CANONICALIZATION.md`.
Etalon implementatsiya: `agent-os/tool-executor/internal/ledger/canonical.go`,
ikkinchisi: `agent-os/platform-core/src/platform_core/shared/canonical.py`.

NEGA SDK'DA UCHINCHI NUSXA BOR. `idempotency_key` avtomatik chiqarilganda u
DETERMINISTIK bo'lishi shart: ayni niyat → ayni kalit, mashina va jarayondan
qat'i nazar. Platformada «ayni niyat» ning ta'rifi allaqachon bor —
`semantic_key` va `action_hash` shu qoidalar bilan hisoblanadi. SDK o'z
qoidasini O'YLAB TOPSA, mijoz tomonidagi «bir niyat» platforma tomonidagi
«bir niyat» dan ajralib ketardi.

Nusxa DRIFT qilmasligi uchun u AYNI umumiy fixture bilan qulflangan:
`contracts/execution/v1/fixtures/canonicalization.json` (tests/test_canonical_contract.py).
Qoida o'zgarsa — fixture o'zgaradi va SDK testi DARHOL qizil bo'ladi.
"""

from __future__ import annotations

import hashlib
import json
import math
import unicodedata
from typing import Any

#: Qiymati KOD bo'lgan va katta-kichik harf farq qilmaydigan maydonlar.
#: `uzs` va `UZS` turli kalit bersa bir to'lov ikki marta ketardi.
_CASE_INSENSITIVE_FIELDS = frozenset({"currency"})


class CanonicalizationError(ValueError):
    """Kalitni beqaror qiladigan qiymat — jim o'tkazilmaydi."""


def canonical(value: Any) -> str:
    """Qiymatning deterministik matn ko'rinishi (kanonik JSON)."""
    return _write(value, "")


def digest(value: Any) -> str:
    """Kanonik shaklning sha256 hex daydjesti."""
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _write(value: Any, field: str) -> str:
    # bool `int` dan OLDIN tekshiriladi — Python'da bool int ning kenja tipi.
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(_text(value, field), ensure_ascii=False)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _number(value)
    if isinstance(value, (list, tuple)):
        # Tartib SAQLANADI: ro'yxatdagi ketma-ketlik ko'pincha ma'noli.
        return "[" + ",".join(_write(v, "") for v in value) + "]"
    if isinstance(value, dict):
        return _obj(value)
    raise CanonicalizationError(
        f"kanonikalash mumkin bo'lmagan tip {type(value).__name__} (maydon {field!r})"
    )


def _obj(m: dict[str, Any]) -> str:
    # null tashlanadi: «maydon yo'q» va «maydon null» — bir xil niyat.
    keys = sorted(k for k, v in m.items() if v is not None)
    parts = [f"{json.dumps(k, ensure_ascii=False)}:{_write(m[k], k)}" for k in keys]
    return "{" + ",".join(parts) + "}"


def _number(f: float) -> str:
    if math.isnan(f) or math.isinf(f):
        raise CanonicalizationError("NaN/Inf kalitga kirmaydi")
    if f == int(f) and abs(f) < 2**53:
        # 100.0 → "100"; Go'ning FormatFloat(-1) bilan bir xil.
        return str(int(f))
    text = repr(f)
    if "e" in text or "E" in text:
        # Eksponentasiz shakl — Go 'f' formatiga mos.
        text = f"{f:.17f}".rstrip("0").rstrip(".")
    if text == "-0":
        return "0"
    return text


def _text(s: str, field: str) -> str:
    s = unicodedata.normalize("NFC", s)
    s = _collapse_spaces(s)
    if _is_case_insensitive(field):
        s = s.upper()
    return s


def _is_case_insensitive(field: str) -> bool:
    if not field:
        return False
    lower = field.lower()
    if lower in _CASE_INSENSITIVE_FIELDS:
        return True
    return any(lower.endswith(f"_{name}") for name in _CASE_INSENSITIVE_FIELDS)


def _collapse_spaces(s: str) -> str:
    """Chekka bo'shliqlar olib tashlanadi, ichkaridagilar bitta probelga."""
    out: list[str] = []
    in_space = True  # boshlanishdagi bo'shliqlarni yutish uchun
    for ch in s:
        if ch.isspace():
            if not in_space:
                out.append(" ")
                in_space = True
            continue
        out.append(ch)
        in_space = False
    return "".join(out).rstrip(" ")
