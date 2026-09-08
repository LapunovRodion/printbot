"""Контрактные тесты DocumentConverter (contracts/printer-backend.md)."""

from __future__ import annotations

from pathlib import Path

import pytest

from printbot.core.conversion.base import ConversionError, DocumentConverter
from printbot.core.conversion.fake import FakeConverter
from printbot.core.models import ErrorCode
from tests.conftest import make_docx_bytes, make_pdf_bytes


def test_fake_satisfies_protocol() -> None:
    assert isinstance(FakeConverter(), DocumentConverter)


def test_libreoffice_satisfies_protocol() -> None:
    from printbot.core.conversion.libreoffice import LibreOfficeConverter

    assert isinstance(LibreOfficeConverter(soffice_path=Path("soffice")), DocumentConverter)


async def test_result_exists_and_source_untouched(tmp_path: Path, fake_converter) -> None:
    source = tmp_path / "doc.docx"
    source.write_bytes(make_docx_bytes())
    before = source.read_bytes()

    result = await fake_converter.to_pdf(source, tmp_path / "out", timeout_s=10)

    assert result.exists() and result.stat().st_size > 0
    assert source.read_bytes() == before


async def test_pdf_input_returned_as_is(tmp_path: Path, fake_converter) -> None:
    source = tmp_path / "doc.pdf"
    source.write_bytes(make_pdf_bytes())

    result = await fake_converter.to_pdf(source, tmp_path / "out", timeout_s=10)

    assert result == source


async def test_failure_is_conversion_error(tmp_path: Path) -> None:
    converter = FakeConverter(fail_with=ErrorCode.CONVERSION_FAILED)
    source = tmp_path / "doc.docx"
    source.write_bytes(make_docx_bytes())

    with pytest.raises(ConversionError) as exc:
        await converter.to_pdf(source, tmp_path / "out", timeout_s=10)
    assert exc.value.code is ErrorCode.CONVERSION_FAILED


async def test_timeout_is_reported_as_timeout_code(tmp_path: Path) -> None:
    """Долгая конвертация прерывается и отображается в ErrorCode.TIMEOUT."""
    from printbot.core.conversion.libreoffice import LibreOfficeConverter

    converter = LibreOfficeConverter(soffice_path=Path("/bin/sh"), extra_args=["-c", "sleep 30"])
    source = tmp_path / "doc.docx"
    source.write_bytes(make_docx_bytes())

    with pytest.raises(ConversionError) as exc:
        await converter.to_pdf(source, tmp_path / "out", timeout_s=0.5)
    assert exc.value.code is ErrorCode.TIMEOUT


def test_isolated_profile_per_call(tmp_path: Path) -> None:
    """Каждому вызову — свой профиль LibreOffice (research.md R2)."""
    from printbot.core.conversion.libreoffice import LibreOfficeConverter

    converter = LibreOfficeConverter(soffice_path=Path("soffice"))
    first = converter.build_command(tmp_path / "a.docx", tmp_path / "out1")
    second = converter.build_command(tmp_path / "b.docx", tmp_path / "out2")

    profiles = [arg for cmd in (first, second) for arg in cmd if "UserInstallation" in arg]
    assert len(profiles) == 2
    assert profiles[0] != profiles[1]
