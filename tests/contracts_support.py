"""Kontrakt fayllariga yagona kirish nuqtasi — SDK testlarining OZIG'I.

⚠ Bu modul ATAYLAB qattiq: kontrakt topilmasa testlar SKIP bo'lmaydi, ular
YIQILADI. Skip — yashil CI'dagi jim yolg'on bo'lardi ("testlar o'tdi"
degan xabar, aslida hech narsa tekshirilmagan). Drift qo'riqchisining
butun ma'nosi shunda: kontrakt o'zgarsa yoki yo'qolsa — SDK DARHOL qizil.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent

#: Qidiruv tartibi: env (CI'da vendor nusxa) → monorepo qo'shnisi →
#: repo ichiga vendor qilingan nusxa (split'dan keyingi hayot).
_CANDIDATES = (
    os.environ.get("DAVIRIX_CONTRACTS_DIR"),
    str(_HERE.parents[2] / "contracts"),
    str(_HERE.parent / "contracts"),
)

EXECUTION_V1 = "platform/execution/v1"
EXECUTION_LEDGER_V1 = "execution/v1"


@lru_cache(maxsize=1)
def contracts_dir() -> Path:
    for candidate in _CANDIDATES:
        if not candidate:
            continue
        path = Path(candidate).expanduser().resolve()
        if (path / EXECUTION_V1 / "execution.schema.json").is_file():
            return path
    raise RuntimeError(
        "Kontraktlar topilmadi. SDK testlari kontrakt fixture'laridan oziqlanadi — "
        "usiz ular MA'NOSIZ. `DAVIRIX_CONTRACTS_DIR` ni ko'rsating yoki "
        f"monorepodagi `contracts/` yonida yurgizing. Qaralgan joylar: {_CANDIDATES}"
    )


def schema(relative: str) -> dict[str, Any]:
    """`platform/execution/v1/execution.schema.json` kabi yo'l bo'yicha sxema."""
    return json.loads((contracts_dir() / relative).read_text(encoding="utf-8"))


def load_json(relative: str) -> Any:
    return json.loads((contracts_dir() / relative).read_text(encoding="utf-8"))


def execution_fixture(name: str) -> dict[str, Any]:
    """Bitta ijro fixture'i (`platform.execution.completed.json`)."""
    return load_json(f"{EXECUTION_V1}/fixtures/{name}")


def execution_fixture_names(*, invalid: bool = False) -> list[str]:
    """BARCHA ijro fixture'lari — ro'yxat qo'lda emas, KATALOGDAN.

    Kontraktga yangi holat qo'shilsa u avtomatik SDK test matritsasiga
    kiradi: SDK uni o'qiy olmasa test qizil bo'ladi.
    """
    base = contracts_dir() / EXECUTION_V1 / "fixtures"
    directory = base / "invalid" if invalid else base
    names = sorted(
        p.name
        for p in directory.glob("platform.execution.*.json")
        if p.is_file()
    )
    if not names:
        raise RuntimeError(f"{directory} da ijro fixture'lari yo'q — kontrakt buzilgan?")
    return names


@lru_cache(maxsize=1)
def _schema_store() -> dict[str, dict[str, Any]]:
    """Barcha sxemalar `$id` (va alias) bo'yicha — cross-file `$ref` uchun."""
    store: dict[str, dict[str, Any]] = {}
    root = contracts_dir()
    for path in sorted(root.rglob("*.schema.json")):
        if {"generated", "node_modules"} & set(path.relative_to(root).parts):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        uris = set()
        sid = data.get("$id")
        if isinstance(sid, str) and sid:
            uris.add(sid)
            uris.add(sid[: -len(".schema.json")] if sid.endswith(".schema.json") else sid + ".schema.json")
        for uri in uris:
            store[uri] = data
    return store


def validator(relative: str):
    """Kontrakt sxemasi uchun Draft 2020-12 validatori (tarmoqsiz `$ref`)."""
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    registry = Registry().with_resources(
        [
            (uri, Resource.from_contents(s, default_specification=DRAFT202012))
            for uri, s in _schema_store().items()
        ]
    )
    return Draft202012Validator(schema(relative), registry=registry)
