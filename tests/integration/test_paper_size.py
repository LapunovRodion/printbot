"""Выбор формата бумаги A4/A3 (шаг появляется только у принтеров с A3)."""

from __future__ import annotations

import pytest

from printbot.bot.routers import printing
from printbot.bot.states import PrintFlow
from printbot.core.models import JobStatus, PaperSize, PrinterConfig
from printbot.core.printing.fake import FakePrinterBackend
from tests.conftest import PRINTER_A, make_docx_bytes
from tests.support import StubCallback, make_document, make_message, make_state

A3_PRINTER = PrinterConfig(key="a3", display_name="Большой", system_name="HP LaserJet M438")


@pytest.fixture
async def a3_services(make_services, tmp_path):
    """Один принтер, умеющий A3 и дуплекс."""
    backend = FakePrinterBackend(
        output_dir=tmp_path / "printed",
        printers={A3_PRINTER.system_name: True},
        a3_printers={A3_PRINTER.system_name},
    )
    services = make_services(printers=(A3_PRINTER,), backend=backend)
    await services.users.get_or_create(1, "Тестовый")
    await services.users.grant_access(1)
    await services.job_service.start(services.printers.system_names)
    try:
        yield services, backend
    finally:
        await services.job_service.stop()


async def _send(services, bot, state, name="doc.docx"):
    message = make_message(1, document=make_document(make_docx_bytes(), name))
    await printing.on_document(message, state, services, bot)
    return message


def _cb(data, message):
    return StubCallback(data=data, message=message, from_user=message.from_user)


async def test_registry_reports_a3_support(a3_services) -> None:
    services, _ = a3_services
    view = (await services.printers.views())[0]
    assert view.supports_a3 is True


async def test_a3_step_offered_and_printed(a3_services, stub_bot) -> None:
    services, backend = a3_services
    state = make_state(1)
    message = await _send(services, stub_bot, state)

    assert await state.get_state() == PrintFlow.choosing_paper.state
    assert "бумаге" in message.last

    await printing.on_paper_chosen(_cb("pp:A3", message), state, services)
    assert await state.get_state() == PrintFlow.choosing_duplex.state

    await printing.on_duplex_chosen(_cb("dx:simplex", message), state, services)
    await printing.on_copies_chosen(_cb("cp:1", message), state, services)

    assert "Бумага: A3" in message.last  # формат виден в сводке до подтверждения

    await printing.on_confirm(_cb("ok:go", message), state, services)
    await services.job_service.wait_idle()

    assert backend.calls[0].options.paper is PaperSize.A3
    job = (await services.jobs.list_for_user(1))[0]
    assert job.paper is PaperSize.A3
    assert job.status is JobStatus.DONE


async def test_a4_still_default_choice(a3_services, stub_bot) -> None:
    services, backend = a3_services
    state = make_state(1)
    message = await _send(services, stub_bot, state)

    await printing.on_paper_chosen(_cb("pp:A4", message), state, services)
    await printing.on_duplex_chosen(_cb("dx:simplex", message), state, services)
    await printing.on_copies_chosen(_cb("cp:1", message), state, services)
    await printing.on_confirm(_cb("ok:go", message), state, services)
    await services.job_service.wait_idle()

    assert backend.calls[0].options.paper is PaperSize.A4


async def test_step_skipped_for_a4_only_printer(services, stub_bot, fake_printer) -> None:
    """У принтера без A3 лишнего вопроса не появляется."""
    await services.users.get_or_create(1, "Тестовый")
    await services.users.grant_access(1)
    await services.job_service.start(services.printers.system_names)
    try:
        state = make_state(1)
        message = await _send(services, stub_bot, state)

        assert await state.get_state() == PrintFlow.choosing_duplex.state
        assert "бумаге" not in " ".join(message.answers)

        data = await state.get_data()
        assert data["paper"] == PaperSize.A4.value
    finally:
        await services.job_service.stop()


async def test_a3_refused_on_a4_only_printer(services, stub_bot) -> None:
    """Даже если нажать старую кнопку A3, задание уйдёт на A4-принтер только как A4."""
    await services.users.get_or_create(1, "Тестовый")
    await services.users.grant_access(1)
    state = make_state(1)
    message = await _send(services, stub_bot, state)

    await printing.on_paper_chosen(_cb("pp:A3", message), state, services)

    assert "только на A4" in message.last
    data = await state.get_data()
    assert data["paper"] == PaperSize.A4.value


async def test_backend_rejects_a3_on_a4_printer(tmp_path) -> None:
    """Контракт бэкенда: A3 на принтер без A3 — ошибка вызывающего кода."""
    from printbot.core.models import DuplexMode, ErrorCode
    from printbot.core.printing.base import PrintError, PrintOptions

    backend = FakePrinterBackend(
        output_dir=tmp_path / "out", printers={PRINTER_A.system_name: True}
    )
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")

    with pytest.raises(PrintError) as exc:
        await backend.print_pdf(
            pdf,
            PrintOptions(
                system_name=PRINTER_A.system_name,
                duplex=DuplexMode.SIMPLEX,
                copies=1,
                paper=PaperSize.A3,
            ),
            timeout_s=5,
        )
    assert exc.value.code is ErrorCode.INTERNAL


async def test_config_can_force_a3(make_services, tmp_path) -> None:
    """Если драйвер молчит про форматы, A3 включается вручную в printers.toml."""
    forced = PrinterConfig(
        key="a3",
        display_name="Большой",
        system_name="HP LaserJet M438",
        supports_a3=True,
    )
    backend = FakePrinterBackend(
        output_dir=tmp_path / "out", printers={forced.system_name: True}, a3_printers=set()
    )
    services = make_services(printers=(forced,), backend=backend)

    assert (await services.printers.views())[0].supports_a3 is True
