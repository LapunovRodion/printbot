"""Юнит-тесты реестра принтеров (US2)."""

from __future__ import annotations

from printbot.core.models import ErrorCode, PrinterConfig
from printbot.core.printers import PrinterRegistry
from printbot.core.printing.fake import FakePrinterBackend
from tests.conftest import PRINTER_A, PRINTER_B


def _registry(backend, *configs) -> PrinterRegistry:
    return PrinterRegistry(configs or (PRINTER_A,), backend, cache_ttl=0.0)


async def test_disabled_printer_is_hidden(tmp_path) -> None:
    backend = FakePrinterBackend(output_dir=tmp_path, printers={PRINTER_A.system_name: True})
    disabled = PrinterConfig(
        key="old", display_name="Старый", system_name="Old", enabled=False
    )
    registry = _registry(backend, PRINTER_A, disabled)
    assert [c.key for c in registry.configs] == ["buh"]


async def test_config_overrides_autodetected_duplex(tmp_path) -> None:
    backend = FakePrinterBackend(output_dir=tmp_path, printers={PRINTER_A.system_name: True})
    forced = PrinterConfig(
        key="buh",
        display_name="Бухгалтерия",
        system_name=PRINTER_A.system_name,
        supports_duplex=False,
    )
    registry = _registry(backend, forced)
    assert (await registry.view(forced)).supports_duplex is False


async def test_autodetects_duplex_when_not_configured(tmp_path) -> None:
    backend = FakePrinterBackend(
        output_dir=tmp_path, printers={PRINTER_A.system_name: True, PRINTER_B.system_name: False}
    )
    registry = _registry(backend, PRINTER_A, PRINTER_B)
    views = {view.key: view.supports_duplex for view in await registry.views()}
    assert views == {"buh": True, "office": False}


async def test_printer_missing_in_system_is_unavailable(tmp_path) -> None:
    backend = FakePrinterBackend(output_dir=tmp_path, printers={})
    registry = _registry(backend, PRINTER_A)
    view = await registry.view(PRINTER_A)
    assert view.available is False
    assert view.reason is ErrorCode.PRINTER_OFFLINE
    await registry.verify_at_startup()  # не должно падать


async def test_status_reason_propagated(tmp_path) -> None:
    backend = FakePrinterBackend(
        output_dir=tmp_path,
        printers={PRINTER_A.system_name: True},
        unavailable={PRINTER_A.system_name: ErrorCode.PAPER_OUT},
    )
    registry = _registry(backend, PRINTER_A)
    view = await registry.view(PRINTER_A)
    assert view.available is False and view.reason is ErrorCode.PAPER_OUT
    assert await registry.available_views() == []


async def test_backend_failure_does_not_raise(tmp_path) -> None:
    class BrokenBackend(FakePrinterBackend):
        async def get_status(self, system_name: str):
            raise RuntimeError("драйвер не отвечает")

    registry = _registry(BrokenBackend(output_dir=tmp_path), PRINTER_A)
    view = await registry.view(PRINTER_A)
    assert view.available is False and view.reason is ErrorCode.PRINTER_ERROR
