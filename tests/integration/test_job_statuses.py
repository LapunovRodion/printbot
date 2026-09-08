"""Статусы заданий и понятные причины отказа (US4, SC-005)."""

from __future__ import annotations

import pytest

from printbot.bot.routers import printing
from printbot.core.conversion.fake import FakeConverter
from printbot.core.models import ErrorCode, JobStatus
from tests.conftest import PRINTER_A, make_docx_bytes
from tests.support import StubCallback, make_document, make_message, make_state


async def _print(services, bot, user_id: int = 1) -> None:
    state = make_state(user_id)
    message = make_message(user_id, document=make_document(make_docx_bytes()))
    await printing.on_document(message, state, services, bot)
    user = message.from_user
    await printing.on_duplex_chosen(
        StubCallback(data="dx:simplex", message=message, from_user=user), state, services
    )
    await printing.on_copies_chosen(
        StubCallback(data="cp:1", message=message, from_user=user), state, services
    )
    await printing.on_confirm(
        StubCallback(data="ok:go", message=message, from_user=user), state, services
    )
    await services.job_service.wait_idle()


@pytest.fixture
async def ready(services):
    await services.users.get_or_create(1, "Тестовый")
    await services.users.grant_access(1)
    await services.job_service.start(services.printers.system_names)
    try:
        yield services
    finally:
        await services.job_service.stop()


@pytest.mark.parametrize(
    ("code", "fragment"),
    [
        (ErrorCode.PAPER_OUT, "бумага"),
        (ErrorCode.PRINTER_OFFLINE, "выключен"),
        (ErrorCode.PAPER_JAM, "замял"),
        (ErrorCode.NO_TONER, "тонер"),
        (ErrorCode.TIMEOUT, "не ответил"),
    ],
)
async def test_print_errors_reach_user(ready, stub_bot, fake_printer, code, fragment) -> None:
    fake_printer.fail_with = code
    await _print(ready, stub_bot)

    job = (await ready.jobs.list_for_user(1))[0]
    assert job.status is JobStatus.FAILED
    assert job.error_code is code
    assert job.finished_at is not None

    notifications = " ".join(stub_bot.texts_for(1))
    assert fragment in notifications
    assert code.value not in notifications  # технический код пользователю не показываем


async def test_conversion_failure_reported(make_services, stub_bot) -> None:
    services = make_services(converter=FakeConverter(fail_with=ErrorCode.CONVERSION_FAILED))
    await services.users.get_or_create(1, "Тестовый")
    await services.users.grant_access(1)
    await services.job_service.start(services.printers.system_names)
    try:
        await _print(services, stub_bot)
    finally:
        await services.job_service.stop()

    job = (await services.jobs.list_for_user(1))[0]
    assert job.status is JobStatus.FAILED
    assert job.error_code is ErrorCode.CONVERSION_FAILED
    assert "подготовить документ" in " ".join(stub_bot.texts_for(1))


async def test_every_job_reaches_final_status(ready, stub_bot, fake_printer) -> None:
    fake_printer.fail_with = ErrorCode.PAPER_OUT
    await _print(ready, stub_bot)
    fake_printer.fail_with = None
    await _print(ready, stub_bot)

    statuses = {job.status for job in await ready.jobs.list_for_user(1)}
    assert statuses == {JobStatus.FAILED, JobStatus.DONE}
    assert await ready.jobs.list_unfinished() == []


async def test_queue_position_reported_on_accept(ready, stub_bot) -> None:
    await _print(ready, stub_bot)
    job_messages = stub_bot.texts_for(1)
    # Уведомление о принятии отправляется ответом в чат, финальное — через бота.
    assert any("отправлено на принтер" in t for t in job_messages)


async def test_status_command_shows_only_own_jobs(ready, stub_bot) -> None:
    from printbot.bot.routers import common

    await _print(ready, stub_bot)
    await ready.users.get_or_create(2, "Другой")
    await ready.users.grant_access(2)
    await _print(ready, stub_bot, user_id=2)

    message = make_message(1, text="/status")
    await common.cmd_status(message, ready)

    assert message.last.count("№") == 1


async def test_large_document_requires_extra_confirmation(ready, stub_bot, fake_printer) -> None:
    from tests.conftest import make_pdf_bytes

    state = make_state(1)
    message = make_message(1, document=make_document(make_pdf_bytes(pages=25), "big.pdf"))
    await printing.on_document(message, state, ready, stub_bot)
    user = message.from_user
    await printing.on_duplex_chosen(
        StubCallback(data="dx:simplex", message=message, from_user=user), state, ready
    )
    await printing.on_copies_chosen(
        StubCallback(data="cp:1", message=message, from_user=user), state, ready
    )
    await printing.on_confirm(
        StubCallback(data="ok:go", message=message, from_user=user), state, ready
    )

    assert "Точно печатаем?" in message.last
    assert fake_printer.calls == []

    await printing.on_large_confirm(
        StubCallback(data="big:go", message=message, from_user=user), state, ready
    )
    await ready.job_service.wait_idle()
    assert len(fake_printer.calls) == 1
    assert fake_printer.calls[0].options.system_name == PRINTER_A.system_name
