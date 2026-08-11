"""SDK semantikasi KONTRAKT fixture'lari bilan qulflanadi.

Bu fayl — drift qo'riqchisi. Fixture ro'yxati QO'LDA yozilmagan: u
`contracts/platform/execution/v1/fixtures/` katalogidan o'qiladi. Kontraktga
yangi holat qo'shilsa u avtomatik shu matritsaga tushadi; SDK uni o'qiy
olmasa — DARHOL qizil.
"""

from __future__ import annotations

import contracts_support as cs
import pytest

from davirix import Execution, ExecutionStatus, OperationStatus, UnverifiedError, Verdict

UNKNOWN_FIXTURE = "platform.execution.completed-lekin-unknown.json"
VERIFIED_FIXTURE = "platform.execution.tasdiqlangan-amal.json"

_ALL = cs.execution_fixture_names()
_ALL_INVALID = cs.execution_fixture_names(invalid=True)


def test_markaziy_fixturelar_kontraktda_bor():
    """Ikki tayanch fixture nomi o'zgarsa — SDK shu yerda qizil bo'ladi."""
    assert UNKNOWN_FIXTURE in _ALL, _ALL
    assert VERIFIED_FIXTURE in _ALL, _ALL


@pytest.mark.parametrize("name", _ALL)
def test_har_fixture_oqiladi(name: str):
    """Har bir yaroqli fixture parse bo'ladi va holat kontraktdan chiqmaydi."""
    payload = cs.execution_fixture(name)
    execution = Execution(payload)

    assert execution.status in {s.value for s in ExecutionStatus}
    assert execution.execution_id == payload["execution_id"]
    assert execution.tenant_id == payload["tenant_id"]
    # Xom konvert YO'QOLMAYDI (oldinga muvofiqlik).
    assert execution.raw == payload
    # Hukm har doim hisoblanadi va hech qachon ISTISNO ko'tarmaydi.
    assert isinstance(execution.verdict, Verdict)
    assert isinstance(execution.verified, bool)
    assert len(execution.operations) == len(payload.get("operations", []))


@pytest.mark.parametrize("name", _ALL)
def test_verified_faqat_hamma_amal_tasdiqlanganda(name: str):
    """`verified` — hukm bilan izchil va FAIL-CLOSED (invariant, har fixture uchun)."""
    execution = Execution(cs.execution_fixture(name))
    if execution.verified:
        assert execution.status == ExecutionStatus.COMPLETED.value
        assert execution.operations_reported
        assert all(op.verified for op in execution.operations)
        assert execution.verdict in (Verdict.VERIFIED, Verdict.NO_ACTIONS)
    else:
        assert execution.verdict not in (Verdict.VERIFIED, Verdict.NO_ACTIONS)


# ── ⚡ SDK dizaynining markazi ───────────────────────────────────────────


def test_completed_lekin_unknown_verified_false():
    """MEZON 3: ijro `completed`, amal `UNKNOWN` → `verified is False`."""
    execution = Execution(cs.execution_fixture(UNKNOWN_FIXTURE))

    assert execution.status == "completed"          # model javob berdi
    assert execution.verified is False              # ⚡ amal tasdiqlanmagan
    assert execution.verdict is Verdict.UNKNOWN
    assert execution.text  # javob matni bor — lekin u isbot emas

    (operation,) = execution.operations
    assert operation.status == OperationStatus.UNKNOWN.value == "UNKNOWN"
    assert operation.capability_id == "notification.send_sms"
    assert operation.verified is False
    assert operation.resend_forbidden is True       # qayta yuborish TAQIQ
    assert execution.unknown_operations == (operation,)


def test_unknown_istisno_emas():
    """QOIDA 2: `UNKNOWN` — ma'lumot, xato EMAS. Parse ISTISNO ko'tarmaydi."""
    payload = cs.execution_fixture(UNKNOWN_FIXTURE)

    execution = Execution(payload)  # istisno bo'lsa — shu yerda yiqiladi
    # O'qish yo'llarining HECH BIRI istisno ko'tarmaydi:
    assert execution.text is not None
    assert execution.verdict is Verdict.UNKNOWN
    assert execution.unverified_operations
    assert execution.explain()

    # Istisno FAQAT mijoz OSHKORA talab qilganda:
    with pytest.raises(UnverifiedError) as info:
        execution.require_verified()
    assert info.value.retryable is False  # qayta yuborish taqiqi — kodda


def test_tasdiqlangan_amal_verified_true():
    """MEZON 4: manbadan tasdiqlangan amal → `verified is True`."""
    execution = Execution(cs.execution_fixture(VERIFIED_FIXTURE))

    assert execution.status == "completed"
    assert execution.verified is True
    assert execution.verdict is Verdict.VERIFIED

    (operation,) = execution.operations
    assert operation.status == "VERIFIED"
    assert operation.verification_method == "READ_AFTER_WRITE"
    assert operation.verification_evidence == "eskiz:msg-8812@DELIVERED"
    assert operation.resend_forbidden is False
    assert execution.require_verified() is execution


def test_operations_bermagan_server_verified_bermaydi():
    """FAIL-CLOSED: `operations[]` YO'Q — «bilmadim», «ha» EMAS.

    `platform.execution.completed.json` — eski (yoki kontraktdan orqada
    qolgan) server javobi: `operations` maydoni umuman yo'q. Bunday javobni
    «bajarildi» deb o'qish — aynan SDK to'sadigan yolg'on.
    """
    execution = Execution(cs.execution_fixture("platform.execution.completed.json"))

    assert execution.status == "completed"
    assert execution.operations_reported is False
    assert execution.verdict is Verdict.UNREPORTED
    assert execution.verified is False


def test_bosh_operations_yozuv_amali_yoqligini_bildiradi():
    """`operations: []` — server AYTDI: yozuv amali bo'lmagan (faqat javob)."""
    payload = dict(cs.execution_fixture("platform.execution.completed.json"))
    payload["operations"] = []

    execution = Execution(payload)
    assert execution.operations_reported is True
    assert execution.verdict is Verdict.NO_ACTIONS
    assert execution.verified is True


@pytest.mark.parametrize(
    "name", [n for n in _ALL if n not in {UNKNOWN_FIXTURE, VERIFIED_FIXTURE}]
)
def test_tugallanmagan_ijro_verified_bermaydi(name: str):
    """Qolgan holatlar (created/failed/cancelled/waiting) — hech qachon verified."""
    execution = Execution(cs.execution_fixture(name))
    if execution.status != "completed":
        assert execution.verified is False
        assert execution.verdict is Verdict.NOT_COMPLETED


def test_notanish_amal_holati_tasdiq_bermaydi():
    """FAIL-CLOSED: kontraktda YO'Q holat (`DONE`) — hech qachon «bajarildi».

    Manba: `fixtures/invalid/platform.execution.nomalum-amal-holati.json` —
    ataylab buzuq kontrakt fixture'i. Yangi/noto'g'ri server qiymati SDK
    tomonidan «muvaffaqiyat» deb TALQIN QILINMAYDI.
    """
    name = "platform.execution.nomalum-amal-holati.json"
    assert name in _ALL_INVALID, _ALL_INVALID
    payload = cs.load_json(f"{cs.EXECUTION_V1}/fixtures/invalid/{name}")

    execution = Execution(payload)
    (operation,) = execution.operations

    assert operation.status == "DONE"
    assert operation.known_status is False
    assert operation.verified is False
    assert operation.resend_forbidden is True   # ma'nosi noma'lum → yubormaymiz
    assert execution.verified is False
    assert execution.verdict is Verdict.UNKNOWN


def test_verified_lekin_verification_method_none_ishonchsiz():
    """Ziddiyat (`VERIFIED` + `NONE`) — ishonchsiz tomon tanlanadi.

    Kontrakt: `verification_method: NONE` — «tasdiqlanmagan; bunday amal
    tasdiqlangan deb ATALMAYDI».
    """
    payload = dict(cs.execution_fixture(VERIFIED_FIXTURE))
    payload["operations"] = [
        {**payload["operations"][0], "verification_method": "NONE"}
    ]

    execution = Execution(payload)
    assert execution.operations[0].verified is False
    assert execution.verified is False


# ── amal qoplamasi: uchinchi holat — «BILMAYMIZ» ────────────────────────

_COVERAGE = [n for n in _ALL if "operations_coverage" in cs.execution_fixture(n)]

#: Qoplama — kontraktga KEYINROQ qo'shilgan (additiv) maydon. Eski teg bilan
#: yurgizilganda bu matritsa bo'sh bo'ladi va SABABI ochiq aytiladi; semantika
#: baribir quyidagi ikki inline test bilan qulflangan.
_COVERAGE_PARAMS = _COVERAGE or [
    pytest.param(
        None,
        marks=pytest.mark.skip(
            reason="bu kontrakt versiyasida `operations_coverage` fixture'i yo'q "
            "— semantika inline testlar bilan qulflangan"
        ),
    )
]


@pytest.mark.parametrize("name", _COVERAGE_PARAMS)
def test_qoplama_kontrakt_fixturelarida(name: str):
    """Qoplama bergan har fixture uchun invariant (ro'yxat KATALOGDAN)."""
    payload = cs.execution_fixture(name)
    execution = Execution(payload)
    coverage = execution.coverage
    assert coverage is not None

    if coverage.complete:
        # To'liq qoplama: `operations` bo'lsa unga ISHONILADI.
        assert execution.operations_reported is ("operations" in payload)
        assert coverage.degraded_reasons == ()
    else:
        # ⚡ «Bilmaymiz» — `verified` HECH QACHON True bermaydi.
        assert execution.operations_reported is False
        assert execution.verified is False
        assert execution.verdict is Verdict.UNREPORTED
        assert coverage.degraded_reasons  # sababsiz «bilmayman» — foydasiz


def test_qoplama_toliq_emas_bosh_massivga_ishonmaydi():
    """Server YOLG'ON juftlik yuborsa (`complete:false` + `operations: []`).

    Kontrakt buni sxema darajasida taqiqlaydi
    (`fixtures/invalid/platform.execution.qoplama-yolgon-bosh-massiv.json`),
    lekin SDK himoyasi sxemaga TAYANMAYDI: bo'sh massiv «amal yo'q» degan
    ma'noni beradi va aynan shu yerda u YOLG'ON bo'lardi.
    """
    payload = dict(cs.execution_fixture("platform.execution.completed.json"))
    payload["operations"] = []
    payload["operations_coverage"] = {
        "complete": False,
        "degraded_reasons": ["ledger_unavailable"],
    }

    execution = Execution(payload)
    assert execution.verdict is Verdict.UNREPORTED   # NO_ACTIONS EMAS
    assert execution.verified is False
    assert execution.coverage.degraded_reasons == ("ledger_unavailable",)


def test_qoplamasiz_javob_eski_serverdek_ishlaydi():
    """Qoplama maydoni umuman bo'lmasa — xatti-harakat O'ZGARMAYDI (additiv)."""
    payload = dict(cs.execution_fixture("platform.execution.tasdiqlangan-amal.json"))
    payload.pop("operations_coverage", None)

    execution = Execution(payload)
    assert execution.coverage is None
    assert execution.verified is True
