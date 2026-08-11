"""QOIDA 1: mijoz `completed` ≠ «bajarildi» ni E'TIBORSIZ QOLDIRA OLMASIN.

To'rt to'siq — har biri shu yerda isbotlanadi:
  1. `bool(execution)`  → TypeError
  2. `.success/.ok/.done/...` → AttributeError (ko'rsatma bilan)
  3. `.verified` fail-closed (test_contract_fixtures.py)
  4. o'qilmagan tasdiqlanmagan amal → WARNING
"""

from __future__ import annotations

import gc
import logging

import contracts_support as cs
import pytest

from davirix import Execution, UnverifiedError, Verdict, set_unverified_warning

UNKNOWN = "platform.execution.completed-lekin-unknown.json"
VERIFIED = "platform.execution.tasdiqlangan-amal.json"


def test_bool_qilib_bolmaydi():
    """`if natija:` — «completed» ni «bajarildi» deb o'qishning eng qisqa yo'li."""
    execution = Execution(cs.execution_fixture(UNKNOWN))

    with pytest.raises(TypeError) as info:
        bool(execution)
    assert "verified" in str(info.value)

    with pytest.raises(TypeError):
        if execution:  # noqa: SIM103 - ataylab: mijoz aynan shunday yozadi
            pass


@pytest.mark.parametrize(
    "name", ["success", "ok", "done", "is_done", "completed", "executed", "delivered"]
)
def test_yolgon_nomlar_yoq(name: str):
    """Bunday xossa YO'Q, chunki bunday YAGONA javob ham yo'q."""
    execution = Execution(cs.execution_fixture(UNKNOWN))

    with pytest.raises(AttributeError) as info:
        getattr(execution, name)
    message = str(info.value)
    assert "verified" in message and "status" in message


def test_notanish_nom_oddiy_attributeerror():
    execution = Execution(cs.execution_fixture(UNKNOWN))
    with pytest.raises(AttributeError):
        execution.mavjud_emas


def _fixture(name: str, marker: str) -> dict:
    """Fixture nusxasi UNIKAL id bilan — boshqa testning axlati aralashmasin."""
    payload = dict(cs.execution_fixture(name))
    payload["execution_id"] = marker
    return payload


def _warned(caplog, marker: str) -> bool:
    return any(marker in record.getMessage() for record in caplog.records)


def test_oqilmagan_tasdiqlanmagan_amal_ogohlantiradi(caplog):
    """asyncio naqshi: jim yo'qolgan xavf — eng yomon holat."""
    set_unverified_warning(True)
    gc.collect()
    with caplog.at_level(logging.WARNING, logger="davirix"):
        execution = Execution(_fixture(UNKNOWN, "exe_test_oqilmagan"))
        del execution
        gc.collect()

    assert _warned(caplog, "exe_test_oqilmagan"), caplog.text
    assert "TASDIQLANMAGAN" in caplog.text


def test_oqilgan_amal_ogohlantirmaydi(caplog):
    gc.collect()
    with caplog.at_level(logging.WARNING, logger="davirix"):
        execution = Execution(_fixture(UNKNOWN, "exe_test_oqilgan"))
        assert execution.verified is False   # kod QARADI
        del execution
        gc.collect()

    assert not _warned(caplog, "exe_test_oqilgan")


def test_tasdiqlangan_ijro_ogohlantirmaydi(caplog):
    gc.collect()
    with caplog.at_level(logging.WARNING, logger="davirix"):
        execution = Execution(_fixture(VERIFIED, "exe_test_tasdiqlangan"))
        del execution
        gc.collect()

    assert not _warned(caplog, "exe_test_tasdiqlangan")


def test_ogohlantirishni_ochirish_mumkin(caplog):
    set_unverified_warning(False)
    gc.collect()
    try:
        with caplog.at_level(logging.WARNING, logger="davirix"):
            execution = Execution(_fixture(UNKNOWN, "exe_test_ochirilgan"))
            del execution
            gc.collect()
        assert not _warned(caplog, "exe_test_ochirilgan")
    finally:
        set_unverified_warning(True)


def test_require_verified_qayta_urinish_huquqi_bermaydi():
    """`UnverifiedError` HECH QACHON retryable emas — qayta yuborish TAQIQ."""
    execution = Execution(cs.execution_fixture(UNKNOWN))
    error = UnverifiedError("x", execution=execution)

    assert error.retryable is False
    with pytest.raises(ValueError):
        error.retryable = True     # kod bilan qulflangan
    assert error.retryable is False


def test_explain_odam_uchun():
    execution = Execution(cs.execution_fixture(UNKNOWN))
    text = execution.explain()
    assert "verdict=unknown" in text
    assert "notification.send_sms:UNKNOWN" in text


def test_repr_amal_holatini_korsatadi():
    execution = Execution(cs.execution_fixture(UNKNOWN))
    assert "UNKNOWN" in repr(execution)
    assert Verdict.UNKNOWN.value == "unknown"
