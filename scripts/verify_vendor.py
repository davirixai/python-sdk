#!/usr/bin/env python3
"""Vendor nusxasini tekshiradi — ikki daraja.

⚠ PLATFORMA: kalitlar POSIX shaklida (`as_posix`) va chiqishda EMOJI YO'Q.
   Ikkalasi ham Windows CI da HAQIQIY nosozlik bergan (2026-08-12):
   `str(PurePath)` u yerda `\\` beradi -> 50 kalitning hammasi mos kelmadi;
   `cp1252` konsoli esa `\u274c` ni chiqara olmay skriptni qulatdi va
   ASL xatoni YASHIRDI. Sof-ASCII chiqish shuning uchun.

⚠ IKKI SAVOL ARALASHTIRILMAYDI:

  1. «Nusxa buzilmaganmi?»  — digest bo'yicha, HAR JOYDA ishlaydi.
  2. «Nusxa kanonik manbaga mosmi?» — faqat manba mavjud bo'lganda.

Public CI faqat 1-savolga javob bera oladi (`davirixai/contracts` private).
Shuning uchun u yerda YASHIL bo'lish «kontraktga mos» degani EMAS — bu
farqni jim qoldirish drift'ni yashirardi.

2-savol monorepoda (contracts yonida) yoki teg olganda tekshiriladi:

    python scripts/verify_vendor.py --canonical /yo'l/contracts

Exit: 0 — toza · 1 — farq · 2 — muhit xatosi.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

VENDOR = Path(__file__).resolve().parent.parent / "tests" / "contracts"
MANIFEST = VENDOR / "VENDOR.json"


def digests(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "VENDOR.json":
            # ⚠ `as_posix()` SHART: Windows'da `str(PurePath)` `\\` beradi va
            # Linux'da yasalgan manifest bilan HECH BIR kalit mos kelmaydi.
            out[p.relative_to(root).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--canonical", type=Path, default=None,
                    help="kanonik `contracts/` katalogi (bo'lmasa faqat digest tekshiriladi)")
    args = ap.parse_args()

    if not MANIFEST.is_file():
        print(f"XATO: manifest yo'q: {MANIFEST}", file=sys.stderr)
        return 2
    manifest = json.loads(MANIFEST.read_text())
    recorded = {k: v for k, v in manifest["files"].items() if k != "VENDOR.json"}

    # --- 1-daraja: nusxa buzilmaganmi ---
    actual = digests(VENDOR)
    if actual != recorded:
        for name in sorted(set(recorded) | set(actual)):
            if recorded.get(name) != actual.get(name):
                kind = ("qo'shilgan" if name not in recorded else
                        "o'chirilgan" if name not in actual else "o'zgargan")
                print(f"  [FARQ] {kind}: {name}")
        print("VENDOR NUSXASI BUZILGAN — manifest bilan mos emas.", file=sys.stderr)
        return 1
    print(f"[OK] nusxa butun — {len(recorded)} fayl, manifest bilan mos")

    # --- 2-daraja: kanonik manba bilan ---
    if args.canonical is None:
        print(f"[!] KANONIK TEKSHIRUV YURGIZILMADI — manba berilmadi.")
        print(f"  Nusxa `{manifest['source']}@{manifest['tag']}` dan olingan deb"
              f" QAYD ETILGAN, lekin bu YERDA tasdiqlanmadi.")
        print(f"  Tasdiqlash: python scripts/verify_vendor.py --canonical <contracts>")
        return 0

    src = args.canonical
    if not (src / "platform" / "execution" / "v1").is_dir():
        print(f"XATO: kanonik manba topilmadi: {src}", file=sys.stderr)
        return 2
    farq = []
    for name in sorted(recorded):
        cand = src.joinpath(*name.split("/"))
        if not cand.is_file():
            farq.append(f"  [FARQ] manbada YO'Q: {name}")
        elif hashlib.sha256(cand.read_bytes()).hexdigest() != recorded[name]:
            farq.append(f"  [FARQ] farq qiladi: {name}")
    if farq:
        print("\n".join(farq))
        print(f"NUSXA KANONIK MANBADAN AJRALGAN ({manifest['tag']}).", file=sys.stderr)
        print("Tuzatish: nusxani qayta oling va VENDOR.json ni yangilang.", file=sys.stderr)
        return 1
    print(f"[OK] kanonik manba bilan mos — {manifest['source']}@{manifest['tag']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
