"""Одновременные задания на один принтер (SC-010, FR-016, FR-018)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from printbot.bot.routers import printing
from printbot.core.models import ErrorCode, JobStatus
from printbot.core.printing.base import PrintError
from printbot.core.printing.fake import FakePrinterBackend
from tests.conftest import PRINTER_A, make_docx_bytes
from tests.support import StubCallback, make_document, make_message, make_state


class OverlapProbeBackend(FakePrinterBackend):
    """Фиксирует перекрытие вызовов печати — их быть не должно."""

    def __post_init__(self) -> None:
        super().__post_init__()
        self.active = 0
        self.max_active = 0
        self.order: list[str] = []

    async def print_pdf(self, pdf: Path, options, timeout_s: float) -> None:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            await asyncio.sleep(0.02)
            await super().print_pdf(pdf, options, timeout_s)
            self.order.append(pdf.name)
        finally:
            self.active -= 1


@pytest.fixture
async def busy(make_services, tmp_path):
    backend = OverlapProbeBackend(
        output_dir=tmp_path / "printed", printers={PRINTER_A.system_name: True}
    )
    services = make_services(backend=backend)
    for user_id in range(1, 6):
        await services.users.get_or_create(user_id, f"Пользователь {user_id}")
        await services.users.grant_access(user_id)
    await services.job_service.start(services.printers.system_names)
    try:
        yield services, backend
    finally:
        await services.job_service.stop()


async def _submit(services, bot, user_id: int) -> None:
    state = make_state(user_id)
    message = make_message(
        user_id, document=make_document(make_docx_bytes(), f"doc-{user_id}.docx")
    )
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


async def test_five_simultaneous_jobs_are_printed_sequentially(busy, stub_bot) -> None:
    services, backend = busy

    await asyncio.gather(*(_submit(services, stub_bot, user_id) for user_id in range(1, 6)))
    await services.job_service.wait_idle()

    assert backend.max_active == 1, "задания разных пользователей печатались одновременно"
    assert len(backend.calls) == 5
    assert len(set(backend.order)) == 5

    for user_id in range(1, 6):
        jobs = await services.jobs.list_for_user(user_id)
        assert len(jobs) == 1 and jobs[0].status is JobStatus.DONE
        assert any("отправлено на принтер" in text for text in stub_bot.texts_for(user_id))


async def test_temp_files_cleaned_after_burst(busy, stub_bot) -> None:
    services, _ = busy
    await asyncio.gather(*(_submit(services, stub_bot, user_id) for user_id in range(1, 6)))
    await services.job_service.wait_idle()

    leftovers = [p.name for p in services.jobs_root.iterdir()]
    assert leftovers == []


async def test_one_failure_does_not_block_others(busy, stub_bot) -> None:
    services, backend = busy

    original = backend.print_pdf
    calls = {"n": 0}

    async def flaky(pdf, options, timeout_s):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PrintError(ErrorCode.PAPER_OUT, "лоток пуст")
        await original(pdf, options, timeout_s)

    backend.print_pdf = flaky

    await asyncio.gather(*(_submit(services, stub_bot, user_id) for user_id in range(1, 6)))
    await services.job_service.wait_idle()

    statuses = [
        (await services.jobs.list_for_user(user_id))[0].status for user_id in range(1, 6)
    ]
    assert statuses.count(JobStatus.FAILED) == 1
    assert statuses.count(JobStatus.DONE) == 4
