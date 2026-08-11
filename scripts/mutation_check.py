#!/usr/bin/env python3
"""Mutatsiya sinovi — testlar HAQIQATAN qo'riqlayaptimi.

Yashil test to'plami o'z-o'zidan hech narsani isbotlamaydi: u hamma narsani
qabul qilayotgan bo'lishi ham mumkin. Bu skript SDK'ning to'rt qoidasini
ATAYLAB buzadi va har buzilish testlarni QIZIL qilishini talab qiladi.
Mutatsiya "omon qolsa" (testlar yashil qolsa) — skript 1 bilan tugaydi.

    python scripts/mutation_check.py [--verbose]

Manba fayllar JOYIDA o'zgartiriladi va HAR DOIM tiklanadi (`finally`),
oxirida sha256 bilan tiklanish tekshiriladi.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "davirix"


@dataclass(frozen=True)
class Mutation:
    name: str
    why: str
    path: Path
    old: str
    new: str


MUTATIONS: list[Mutation] = [
    Mutation(
        name="verified-har-doim-true",
        why="«bajarildi» ni jim tasdiqlash — SDK keltiradigan eng katta zarar",
        path=SRC / "result.py",
        old="        return self.verdict in _VERIFIED_VERDICTS",
        new="        return True",
    ),
    Mutation(
        name="unknown-istisno-qiladi",
        why="UNKNOWN ni xatoga aylantirish → mijoz `except: retry` yozadi → DUBLIKAT effekt",
        path=SRC / "result.py",
        old="        self._inspected = False",
        new=(
            "        self._inspected = False\n"
            "        for _op in self._operations:\n"
            "            if _op.status == 'UNKNOWN':\n"
            "                raise UnverifiedError('UNKNOWN amal', operations=(_op,))"
        ),
    ),
    Mutation(
        name="operations-yoqligi-xavfsiz-deb-hisoblanadi",
        why="`operations[]` bermagan serverni «amal yo'q» deb o'qish — fail-open",
        path=SRC / "result.py",
        old="        self._operations_reported = isinstance(ops, list)",
        new="        self._operations_reported = True",
    ),
    Mutation(
        name="toliq-bolmagan-qoplamaga-ishonadi",
        why="`complete:false` bilan kelgan bo'sh massivni «amal yo'q» deb o'qish — yolg'on",
        path=SRC / "result.py",
        old=(
            "        self._operations_reported = isinstance(ops, list) and (\n"
            "            self._coverage is None or self._coverage.complete\n"
            "        )"
        ),
        new="        self._operations_reported = isinstance(ops, list)",
    ),
    Mutation(
        name="notanish-holat-xavfsiz-deb-hisoblanadi",
        why="kontraktda yo'q holatni («DONE») qayta yuborishga ruxsat berish",
        path=SRC / "result.py",
        old="        if not self.known_status:\n            return True\n        return self.status in _RESEND_FORBIDDEN",
        new="        if not self.known_status:\n            return False\n        return self.status in _RESEND_FORBIDDEN",
    ),
    Mutation(
        name="retry-har-qanday-xatoda",
        why="`retryable` shartisiz qayta urinish — takroriy effekt xavfi",
        path=SRC / "client.py",
        old="            if attempt < self._max_retries and is_retryable(error):",
        new="            if attempt < self._max_retries:",
    ),
    Mutation(
        name="idempotentlik-kaliti-tasodifiy",
        why="deterministik bo'lmagan kalit — niyat darajasidagi himoya yo'qoladi",
        path=SRC / "client.py",
        old="    return _KEY_PREFIX + digest(dict(body))",
        new="    return _KEY_PREFIX + __import__('uuid').uuid4().hex",
    ),
]


def _digests() -> dict[str, str]:
    return {
        str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(SRC.rglob("*.py"))
    }


def _run_tests() -> tuple[bool, str]:
    proc = subprocess.run(
        # `-x` YO'Q: qaysi qoida qancha joyda qo'riqlanayotgani ko'rinsin.
        [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0, proc.stdout + proc.stderr


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    before = _digests()

    green, output = _run_tests()
    if not green:
        print("XATO: mutatsiyasiz testlar allaqachon qizil — avval ularni tuzating.\n")
        print(output[-3000:])
        return 2
    print("asos: testlar yashil\n")

    survivors: list[str] = []
    for mutation in MUTATIONS:
        source = mutation.path.read_text(encoding="utf-8")
        if mutation.old not in source:
            print(f"XATO: mutatsiya nishoni topilmadi ({mutation.name}) — skript eskirgan")
            return 2
        try:
            mutation.path.write_text(
                source.replace(mutation.old, mutation.new, 1), encoding="utf-8"
            )
            passed, output = _run_tests()
        finally:
            mutation.path.write_text(source, encoding="utf-8")

        failures = [
            line for line in output.splitlines() if line.startswith(("FAILED", "ERROR"))
        ]
        totals = [line for line in output.splitlines() if " failed" in line or " error" in line]
        status = "OMON QOLDI ⛔" if passed else "o'ldirildi ✓"
        print(f"[{status}] {mutation.name}\n    nega muhim: {mutation.why}")
        for line in totals[-1:] or failures[:1]:
            print(f"    natija: {line.strip()}")
        for line in failures[:3]:
            print(f"    {line.strip()}")
        if len(failures) > 3:
            print(f"    ... yana {len(failures) - 3} ta")
        if args.verbose:
            print(output[-1500:])
        if passed:
            survivors.append(mutation.name)
        print()

    after = _digests()
    if before != after:
        print("XATO: manba tiklanmadi — qo'lda tekshiring!")
        return 2
    print("manba tiklandi (sha256 mos)")

    if survivors:
        print(f"\n⛔ {len(survivors)} mutatsiya omon qoldi: {', '.join(survivors)}")
        print("Testlar bu qoidalarni QO'RIQLAMAYAPTI.")
        return 1
    print(f"\n✓ {len(MUTATIONS)} mutatsiyaning hammasi o'ldirildi")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
