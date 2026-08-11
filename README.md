# davirix — Python SDK

Davirix agent platformasi uchun rasmiy Python mijozi (`/v1/executions`).

> ## ⚠ `completed` — «bajarildi» degani EMAS
>
> `status: completed` — **model javob berdi** degani. Amal (SMS ketdimi,
> karta yangilandimi) bajarildimi — bu **faqat `operations[]`** da ko'rinadi.
> Konnektor timeout bersa amal `UNKNOWN` bo'lib qoladi, model esa baribir
> chiroyli javob yozishi mumkin.
>
> Shuning uchun bu SDK'da `execution.success` yo'q va `bool(execution)`
> **TypeError** beradi. Yagona «bajarildimi» javobi — `execution.verified`.

## O'rnatish

```bash
pip install davirix          # PyPI (hali nashr qilinmagan — pastga qarang)
pip install -e .             # monorepodan
```

Yagona runtime bog'liqlik — `httpx`.

## 10 qatorlik misol

```python
from davirix import Davirix

dx = Davirix(tenant_id="acme", actor="service:billing")   # kalit: DAVIRIX_API_KEY
n = dx.run(agent_id="mkbank-support", input={"text": "Mijozga SMS yubor"})

print(n.status)      # "completed"          ← MODEL javob berdi
print(n.verified)    # False                ← AMAL tasdiqlanmagan
print(n.verdict)     # Verdict.UNKNOWN      ← nega: natija noma'lum

if not n.verified:
    for op in n.unknown_operations:
        print(op.capability_id, op.status)  # notification.send_sms UNKNOWN
        # ⛔ QAYTA YUBORMANG — reconciliation aniqlaydi
```

`n.text` — model javobi. U **matn**, amal isboti emas.

## To'rtta qoida

**1. `completed` ≠ «bajarildi».** `verified` — fail-closed: `operations[]`
kelmasa ham, holat tanish bo'lmasa ham **False**. «Bilmadim» hech qachon
«ha» ga aylanmaydi.

```python
n.status        # ijro holati (xom satr)
n.verified      # BARCHA yozuv amallari manbadan tasdiqlanganmi
n.verdict       # nega: verified · no_actions · unknown · failed_action ·
                #       pending_action · unreported · not_completed
n.operations    # typed amallar ro'yxati
n.coverage      # `operations[]` ga ishonish mumkinmi (degraded_reasons bilan)
n.require_verified()   # tasdiq SHART bo'lgan joyda — UnverifiedError
```

Amal holatining **uch** holati aralashtirilmaydi:

| Javob | Ma'no | `verified` |
|---|---|---|
| `operations: [...]` | bilamiz | amallarga qarab |
| `operations: []` | yozuv amali bo'lmagan | `True` |
| `operations` yo'q / `coverage.complete: false` | **bilmaymiz** | `False` |

Tasdiqlanmagan amal bilan tugagan ijroni kod umuman o'qimasa, SDK
`davirix` logger'iga WARNING yozadi (asyncio'ning «Task exception was never
retrieved» naqshi). O'chirish: `set_unverified_warning(False)`.

**2. `UNKNOWN` — istisno EMAS.** SDK u uchun hech qachon istisno
ko'tarmaydi. Sabab amaliy: istisno ko'rgan joyda mijoz `except: retry`
yozadi va **dublikat effekt** yaratadi. `UNKNOWN` dan yagona chiqish yo'li —
reconciliation.

**3. `idempotency_key` avtomatik va barqaror.**

```python
dx.run(agent_id="x", input={"text": "..."})                    # kalit argumentlardan
dx.run(agent_id="x", input={"text": "..."}, key="buyurtma-42") # yoki mijoz beradi
```

Kalit so'rov tanasining **kanonik** shaklidan chiqariladi — platformaning
`semantic_key`/`action_hash` bilan **ayni** qoidalar
(`contracts/execution/v1/CANONICALIZATION.md`). Ayni argumentlar → ayni kalit
→ server ikkinchi ijro yaratmaydi. Shu bois tarmoq uzilganda **qo'lda qayta
chaqirish xavfsiz**.

**4. Retry faqat `retryable: true` da.**

| Holat | SDK qiladi |
|---|---|
| `429` (+ `Retry-After`) | qayta urinadi, serverning kutish vaqtini hurmat qiladi |
| `502/503` + `retryable: true` | qayta urinadi |
| `502/503` `retryable`siz | **urinmaydi** — «vaqtinchalikdir» deb taxmin qilinmaydi |
| `409 / 422 / 403 / 404` | urinmaydi (holat qayta urinishdan o'zgarmaydi) |
| ulanish uzildi (javob yo'q) | **urinmaydi** — POST bajarilgan bo'lishi mumkin |
| ijro `failed`, `error.retryable: true` | **avtomatik qayta yurgizilmaydi** — yangi ijro = yangi effekt; qaror mijozniki |

## API

```python
dx.run(...)      # yaratadi va yakunlanguncha kutadi (yoki approval kutishigacha)
dx.start(...)    # yaratadi va darhol qaytadi
dx.get(id)       # holat
dx.wait(x)       # kuzatish
dx.cancel(id)    # kooperativ bekor qilish
```

`run()` istisno ko'tarmaydi ijro **holati** uchun: `failed` ham, `cancelled`
ham, `waiting_for_approval` ham — bu **ma'lumot**, xato emas. Istisnolar
faqat transport/protokol uchun (`errors.py`).

Kutish budjeti tugasa — `ExecutionTimeout`: ijro **serverda davom etmoqda**,
`dx.get(execution_id)` bilan kuzatishda davom eting.

## Sir

`api_key` — konstruktor argumenti yoki `DAVIRIX_API_KEY`. Kodga yozilmaydi,
`repr()` ga tushmaydi, xato matniga tushmaydi. Kalit umuman berilmasa mijoz
**qurilmaydi** (jim autentifikatsiyasiz so'rov yo'q).

## Testlar — kontrakt fixture'laridan

Testlar `contracts/platform/execution/v1/fixtures/` dan **to'g'ridan-to'g'ri**
oziqlanadi; ro'yxat qo'lda emas, katalogdan o'qiladi. Kontrakt o'zgarsa SDK
darhol qizil bo'ladi.

```bash
pip install -e ".[dev]"
pytest -q
python scripts/mutation_check.py     # qoidalarni buzuvchi o'zgarish qizil bo'lishini isbotlaydi
```

Kontraktlar boshqa joyda bo'lsa: `DAVIRIX_CONTRACTS_DIR=/yo'l/contracts pytest -q`.

## Holat (0.1.0)

* Sinxron mijoz. `async` mijoz — keyingi versiya.
* `POST/GET/cancel` qamrab olingan; `events`/`stream`/`resume`/`feedback`/
  `handoff` — keyingi versiya.
* **PyPI'ga hali nashr qilinmagan.** Nashr — alohida qadam.
