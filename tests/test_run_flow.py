"""`run()` — yaratish + kuzatish. Jonli server YO'Q: `httpx.MockTransport`.

Soxta server javoblari ham KONTRAKT fixture'laridan olinadi — ya'ni oqim
testlari ham drift qo'riqchisi ostida.
"""

from __future__ import annotations

import contracts_support as cs
import httpx
import pytest

from davirix import ExecutionTimeout, Verdict

CREATED = cs.execution_fixture("platform.execution.created.json")
UNKNOWN = cs.execution_fixture("platform.execution.completed-lekin-unknown.json")
VERIFIED = cs.execution_fixture("platform.execution.tasdiqlangan-amal.json")
FAILED = cs.execution_fixture("platform.execution.failed.json")
WAITING = cs.execution_fixture("platform.execution.waiting-for-approval.json")

RUNNING = {**CREATED, "status": "running"}
ARGS = dict(agent_id="mkbank-support", input={"text": "Mijozga SMS yubor"})


def _server(*get_payloads):
    """POST → 201 running, keyin har GET navbatdagi holatni beradi."""
    queue = list(get_payloads)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(201, json=RUNNING)
        return httpx.Response(200, json=queue.pop(0) if len(queue) > 1 else queue[0])

    return handler


def test_run_kutadi_va_completed_lekin_unknown_qaytaradi(make_client, recorder):
    """Uchidan-uchiga: `completed` qaytdi, lekin `verified is False`."""
    execution = make_client(_server(RUNNING, UNKNOWN)).run(**ARGS)

    assert execution.status == "completed"
    assert execution.verified is False
    assert execution.verdict is Verdict.UNKNOWN
    assert execution.unknown_operations[0].capability_id == "notification.send_sms"

    methods = [r.method for r in recorder.requests]
    assert methods == ["POST", "GET", "GET"]
    assert recorder.requests[1].url.params["tenant_id"] == execution.tenant_id


def test_run_tasdiqlangan_amalni_tan_oladi(make_client):
    execution = make_client(_server(VERIFIED)).run(**ARGS)
    assert execution.verified is True


def test_failed_ijro_istisno_emas_va_qayta_YURGIZILMAYDI(make_client, recorder):
    """`failed` — MA'LUMOT. SDK ijroni O'ZI qayta yurgizmaydi: yangi ijro = yangi effekt.

    Server `retryable: true` desa ham qaror mijozniki: bu tarmoq qayta
    urinishi emas, YANGI ijro (yangi SMS) bo'lardi.
    """
    execution = make_client(_server(FAILED)).run(**ARGS)

    assert execution.status == "failed"
    assert execution.error is not None
    assert execution.error.code == "inference_unavailable"
    assert execution.error.retryable is True   # server shunday dedi
    assert execution.verified is False
    assert [r.method for r in recorder.requests].count("POST") == 1  # bitta ijro


def test_approval_kutayotgan_ijro_qaytariladi(make_client, recorder):
    """Odam qarorini kutish — cheksiz poll qilinmaydi, boshqaruv mijozga qaytadi."""
    execution = make_client(_server(WAITING)).run(**ARGS, wait_timeout=5)

    assert execution.status == "waiting_for_approval"
    assert execution.waiting_for is not None
    assert execution.waiting_for.interrupt_id == "int_7ab1"
    assert execution.is_settled is True


def test_kutish_budjeti_tugasa_ijro_serverda_qoladi(make_client, recorder):
    """Timeout — «bajarilmadi» EMAS. Ijro davom etadi, id qaytariladi."""
    with pytest.raises(ExecutionTimeout) as info:
        make_client(_server(RUNNING)).run(**ARGS, wait_timeout=0)

    error = info.value
    assert error.execution_id == RUNNING["execution_id"]
    assert error.last.status == "running"
    assert error.retryable is False
    assert [r.method for r in recorder.requests].count("POST") == 1


def test_start_kutmaydi(make_client, recorder):
    execution = make_client(_server(UNKNOWN)).start(**ARGS)
    assert execution.status == "running"
    assert [r.method for r in recorder.requests] == ["POST"]


def test_get_va_cancel(make_client, recorder):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/cancel"):
            return httpx.Response(200, json=cs.execution_fixture("platform.execution.cancelled.json"))
        return httpx.Response(200, json=UNKNOWN)

    client = make_client(handler)
    assert client.get("exe_4b7e2200000000000000000000000000").status == "completed"
    assert client.cancel("exe_ffffffffffffffffffffffffffffffff").status == "cancelled"


def test_javob_kontrakt_sxemasiga_mos_boladi(make_client):
    """Soxta server javobi ham kontraktdan chiqmasin (fixture'lar haqiqiy)."""
    execution = make_client(_server(UNKNOWN)).run(**ARGS)
    errors = list(
        cs.validator(f"{cs.EXECUTION_V1}/execution.schema.json").iter_errors(dict(execution.raw))
    )
    assert not errors, [e.message for e in errors]
