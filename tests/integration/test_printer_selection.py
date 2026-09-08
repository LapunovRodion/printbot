"""Выбор принтера (US2)."""

from __future__ import annotations

import pytest

from printbot.bot.routers import printing
from printbot.bot.states import PrintFlow
from printbot.core.models import ErrorCode, PrinterConfig
from tests.conftest import PRINTER_A, PRINTER_B, make_docx_bytes
from tests.support import StubCallback, make_document, make_message, make_state


@pytest.fixture
async def two_printers(make_services, fake_printer):
    services = make_services(printers=(PRINTER_A, PRINTER_B))
    await services.users.get_or_create(1, "Тестовый")
    await services.users.grant_access(1)
    await services.job_service.start(services.printers.system_names)
    try:
        yield services
    finally:
        await services.job_service.stop()


async def _send_doc(services, bot, state, name="doc.docx"):
    message = make_message(1, document=make_document(make_docx_bytes(), name))
    await printing.on_document(message, state, services, bot)
    return message


async def test_choice_offered_and_used(two_printers, stub_bot, fake_printer) -> None:
    state = make_state(1)
    message = await _send_doc(two_printers, stub_bot, state)

    assert await state.get_state() == PrintFlow.choosing_printer.state
    assert "Выберите принтер" in message.last

    cb = StubCallback(data="pr:office", message=message, from_user=message.from_user)
    await printing.on_printer_chosen(cb, state, two_printers)
    await printing.on_duplex_chosen(
        StubCallback(data="dx:simplex", message=message, from_user=message.from_user),
        state,
        two_printers,
    )
    await printing.on_copies_chosen(
        StubCallback(data="cp:1", message=message, from_user=message.from_user),
        state,
        two_printers,
    )
    await printing.on_confirm(
        StubCallback(data="ok:go", message=message, from_user=message.from_user),
        state,
        two_printers,
    )
    await two_printers.job_service.wait_idle()

    assert len(fake_printer.calls) == 1
    assert fake_printer.calls[0].options.system_name == PRINTER_B.system_name


async def test_single_printer_skips_step(services, stub_bot) -> None:
    await services.users.get_or_create(1, "Тестовый")
    await services.users.grant_access(1)
    state = make_state(1)
    message = await _send_doc(services, stub_bot, state)


    assert await state.get_state() == PrintFlow.choosing_duplex.state
    joined = " ".join(message.answers)
    assert "Выберите принтер" not in joined


async def test_unavailable_printer_not_offered(two_printers, stub_bot, fake_printer) -> None:
    fake_printer.unavailable[PRINTER_B.system_name] = ErrorCode.PAPER_OUT
    two_printers.printers.invalidate()

    state = make_state(1)
    await _send_doc(two_printers, stub_bot, state)

    # Остался один доступный принтер — шаг выбора пропускается.
    assert await state.get_state() == PrintFlow.choosing_duplex.state
    data = await state.get_data()
    assert data["printer_system"] == PRINTER_A.system_name


async def test_choosing_unavailable_printer_is_refused(
    two_printers, stub_bot, fake_printer
) -> None:
    state = make_state(1)
    message = await _send_doc(two_printers, stub_bot, state)

    fake_printer.unavailable[PRINTER_B.system_name] = ErrorCode.PRINTER_OFFLINE
    two_printers.printers.invalidate()

    cb = StubCallback(data="pr:office", message=message, from_user=message.from_user)
    await printing.on_printer_chosen(cb, state, two_printers)

    assert "недоступен" in message.last
    assert await state.get_state() == PrintFlow.choosing_printer.state


async def test_no_printers_at_all(make_services, stub_bot, tmp_path) -> None:
    from printbot.core.printing.fake import FakePrinterBackend

    backend = FakePrinterBackend(output_dir=tmp_path / "out", printers={})
    services = make_services(printers=(PRINTER_A,), backend=backend)
    await services.users.get_or_create(1, "Тестовый")
    await services.users.grant_access(1)

    state = make_state(1)
    message = await _send_doc(services, stub_bot, state)

    assert "нет доступных принтеров" in message.last.lower()
    assert await state.get_state() is None


async def test_duplex_hidden_for_simplex_printer(make_services, stub_bot, tmp_path) -> None:
    from printbot.core.printing.fake import FakePrinterBackend

    simplex = PrinterConfig(key="s", display_name="Простой", system_name="SimplexOnly")
    backend = FakePrinterBackend(output_dir=tmp_path / "out", printers={"SimplexOnly": False})
    services = make_services(printers=(simplex,), backend=backend)
    await services.users.get_or_create(1, "Тестовый")
    await services.users.grant_access(1)

    state = make_state(1)
    message = await _send_doc(services, stub_bot, state)

    assert any("нет двусторонней печати" in text for text in message.answers)
    keyboard = [m for m in message.markups if m is not None][-1]
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert "Двусторонняя" not in labels

    await printing.on_duplex_chosen(
        StubCallback(data="dx:duplex", message=message, from_user=message.from_user),
        state,
        services,
    )
    assert "нет двусторонней печати" in message.last
