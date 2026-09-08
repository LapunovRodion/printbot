"""Сквозной путь US1: документ → параметры → подтверждение → печать."""

from __future__ import annotations

from pathlib import Path

import pytest

from printbot.bot.routers import printing
from printbot.core.models import DuplexMode, JobStatus
from tests.conftest import PRINTER_A, make_docx_bytes, make_pdf_bytes
from tests.support import make_document, make_message, make_state


@pytest.fixture
async def flow(services):
    """Готовый пользователь с доступом и запущенными воркерами печати."""
    await services.users.get_or_create(1, "Тестовый Пользователь")
    await services.users.grant_access(1)
    await services.job_service.start(services.printers.system_names)
    try:
        yield services
    finally:
        await services.job_service.stop()


async def _run_flow(
    flow,
    bot,
    payload: bytes,
    file_name: str = "doc.docx",
    duplex: str = "simplex",
    copies: str = "2",
):
    state = make_state(1)
    message = make_message(1, document=make_document(payload, file_name))
    await printing.on_document(message, state, flow, bot)

    from tests.support import StubCallback

    cb_duplex = StubCallback(data=f"dx:{duplex}", message=message, from_user=message.from_user)
    await printing.on_duplex_chosen(cb_duplex, state, flow)

    cb_copies = StubCallback(data=f"cp:{copies}", message=message, from_user=message.from_user)
    await printing.on_copies_chosen(cb_copies, state, flow)

    cb_confirm = StubCallback(data="ok:go", message=message, from_user=message.from_user)
    await printing.on_confirm(cb_confirm, state, flow)

    await flow.job_service.wait_idle()
    return state, message


async def test_docx_printed_with_chosen_options(flow, stub_bot, fake_printer) -> None:
    _, message = await _run_flow(flow, stub_bot, make_docx_bytes(), duplex="duplex", copies="3")

    assert len(fake_printer.calls) == 1
    call = fake_printer.calls[0]
    assert call.options.copies == 3
    assert call.options.duplex is DuplexMode.DUPLEX_LONG
    assert call.options.system_name == PRINTER_A.system_name

    jobs = await flow.jobs.list_for_user(1)
    assert len(jobs) == 1 and jobs[0].status is JobStatus.DONE
    assert any("отправлено на принтер" in text for text in stub_bot.texts_for(1))


async def test_pdf_printed_through_same_flow(flow, stub_bot, fake_printer) -> None:
    await _run_flow(flow, stub_bot, make_pdf_bytes(pages=3), "report.pdf", "simplex", "1")

    assert len(fake_printer.calls) == 1
    assert fake_printer.calls[0].options.duplex is DuplexMode.SIMPLEX
    job = (await flow.jobs.list_for_user(1))[0]
    assert job.status is JobStatus.DONE
    assert job.page_count == 3


async def test_workspace_removed_after_job(flow, stub_bot, tmp_path: Path) -> None:
    await _run_flow(flow, stub_bot, make_docx_bytes())
    leftovers = [p for p in flow.jobs_root.iterdir()] if flow.jobs_root.exists() else []
    assert leftovers == []


async def test_unsupported_format_is_not_printed(flow, stub_bot, fake_printer) -> None:
    state = make_state(1)
    message = make_message(1, document=make_document(b"random bytes here", "table.xlsx"))
    await printing.on_document(message, state, flow, stub_bot)

    assert "не поддерживается" in message.last.lower()
    assert fake_printer.calls == []
    assert await state.get_state() is None


async def test_too_large_file_rejected_before_download(flow, stub_bot) -> None:
    state = make_state(1)
    document = make_document(make_docx_bytes(), "big.docx")
    document.file_size = flow.config.settings.max_file_bytes + 1
    message = make_message(1, document=document)

    await printing.on_document(message, state, flow, stub_bot)

    assert "слишком большой" in message.last.lower()
    assert await state.get_state() is None


async def test_copies_out_of_range_rejected(flow, stub_bot) -> None:
    state = make_state(1)
    message = make_message(1, document=make_document(make_docx_bytes()))
    await printing.on_document(message, state, flow, stub_bot)

    from tests.support import StubCallback

    await printing.on_duplex_chosen(
        StubCallback(data="dx:simplex", message=message, from_user=message.from_user), state, flow
    )
    text_message = make_message(1, text="0")
    await printing.on_copies_text(text_message, state, flow)
    assert "от 1 до" in text_message.last

    text_message = make_message(1, text="пять")
    await printing.on_copies_text(text_message, state, flow)
    assert "от 1 до" in text_message.last


async def test_new_file_replaces_unfinished_draft(flow, stub_bot) -> None:
    state = make_state(1)
    first = make_message(1, document=make_document(make_docx_bytes(), "first.docx"))
    await printing.on_document(first, state, flow, stub_bot)

    second = make_message(1, document=make_document(make_docx_bytes(), "second.docx"))
    await printing.on_document(second, state, flow, stub_bot)

    assert any("отменено" in text.lower() for text in second.answers)
    data = await state.get_data()
    assert data["file_name"] == "second.docx"


async def test_cancel_removes_draft(flow, stub_bot, fake_printer) -> None:
    state = make_state(1)
    message = make_message(1, document=make_document(make_docx_bytes()))
    await printing.on_document(message, state, flow, stub_bot)

    from tests.support import StubCallback

    await printing.on_duplex_chosen(
        StubCallback(data="dx:simplex", message=message, from_user=message.from_user), state, flow
    )
    await printing.on_copies_chosen(
        StubCallback(data="cp:1", message=message, from_user=message.from_user), state, flow
    )
    await printing.on_confirm(
        StubCallback(data="ok:cancel", message=message, from_user=message.from_user), state, flow
    )

    assert await state.get_state() is None
    assert fake_printer.calls == []
    assert list(flow.jobs_root.iterdir()) == []
