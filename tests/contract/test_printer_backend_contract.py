"""Контрактные тесты PrinterBackend (contracts/printer-backend.md)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from printbot.core.models import DuplexMode, ErrorCode
from printbot.core.printing.base import (
    PrinterBackend,
    PrintError,
    PrintOptions,
)
from printbot.core.printing.fake import FakePrinterBackend
from tests.conftest import PRINTER_A, make_pdf_bytes


@pytest.fixture
def pdf(tmp_path: Path) -> Path:
    path = tmp_path / "doc.pdf"
    path.write_bytes(make_pdf_bytes())
    return path


def test_fake_satisfies_protocol(tmp_path: Path) -> None:
    assert isinstance(FakePrinterBackend(output_dir=tmp_path), PrinterBackend)


def test_windows_backend_satisfies_protocol() -> None:
    from printbot.core.printing.windows import WindowsPrinterBackend

    assert isinstance(WindowsPrinterBackend(sumatra_path=Path("SumatraPDF.exe")), PrinterBackend)


async def test_options_passed_once(fake_printer, pdf: Path) -> None:
    """Копии и дуплекс передаются устройству ровно один раз (без цикла по копиям)."""
    options = PrintOptions(
        system_name=PRINTER_A.system_name, duplex=DuplexMode.DUPLEX_LONG, copies=3
    )
    await fake_printer.print_pdf(pdf, options, timeout_s=10)

    assert len(fake_printer.calls) == 1
    assert fake_printer.calls[0].options.copies == 3
    assert fake_printer.calls[0].options.duplex is DuplexMode.DUPLEX_LONG


async def test_duplex_on_simplex_printer_is_internal_error(tmp_path: Path, pdf: Path) -> None:
    backend = FakePrinterBackend(output_dir=tmp_path / "out", printers={"Simplex": False})
    options = PrintOptions(system_name="Simplex", duplex=DuplexMode.DUPLEX_LONG, copies=1)

    with pytest.raises(PrintError) as exc:
        await backend.print_pdf(pdf, options, timeout_s=10)
    assert exc.value.code is ErrorCode.INTERNAL


async def test_failure_is_print_error_with_code(tmp_path: Path, pdf: Path) -> None:
    backend = FakePrinterBackend(
        output_dir=tmp_path / "out",
        printers={PRINTER_A.system_name: True},
        fail_with=ErrorCode.PAPER_OUT,
    )
    options = PrintOptions(system_name=PRINTER_A.system_name, duplex=DuplexMode.SIMPLEX, copies=1)

    with pytest.raises(PrintError) as exc:
        await backend.print_pdf(pdf, options, timeout_s=10)
    assert exc.value.code is ErrorCode.PAPER_OUT


async def test_status_does_not_raise_for_unknown_printer(fake_printer) -> None:
    status = await fake_printer.get_status("нет такого")
    assert status.available is False
    assert status.reason is ErrorCode.PRINTER_OFFLINE


async def test_list_printers_reports_duplex_support(fake_printer) -> None:
    infos = {info.system_name: info.supports_duplex for info in await fake_printer.list_printers()}
    assert infos[PRINTER_A.system_name] is True


def test_sumatra_command_contains_all_options() -> None:
    """Проверяем формирование команды печати без запуска процесса."""
    from printbot.core.printing.windows import WindowsPrinterBackend

    backend = WindowsPrinterBackend(sumatra_path=Path("SumatraPDF.exe"))
    command = backend.build_command(
        Path("doc.pdf"),
        PrintOptions(system_name="Pantum P5100", duplex=DuplexMode.DUPLEX_LONG, copies=3),
    )
    joined = " ".join(command)

    assert "-print-to" in joined and "Pantum P5100" in joined
    assert "duplexlong" in joined
    assert "3x" in joined
    assert "-silent" in joined and "-exit-when-done" in joined


def test_sumatra_command_simplex() -> None:
    from printbot.core.printing.windows import WindowsPrinterBackend

    backend = WindowsPrinterBackend(sumatra_path=Path("SumatraPDF.exe"))
    settings = " ".join(
        backend.build_command(
            Path("doc.pdf"),
            PrintOptions(system_name="P", duplex=DuplexMode.SIMPLEX, copies=1),
        )
    )
    assert "simplex" in settings
    assert "duplex" not in settings.replace("duplexlong", "")


@pytest.mark.skipif(sys.platform != "win32", reason="требуется Windows")
async def test_real_backend_lists_printers() -> None:  # pragma: no cover - только на хосте
    from printbot.core.printing.windows import WindowsPrinterBackend

    backend = WindowsPrinterBackend(sumatra_path=Path("tools/SumatraPDF.exe"))
    assert isinstance(await backend.list_printers(), list)
