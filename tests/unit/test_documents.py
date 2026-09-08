"""Юнит-тесты валидации документов (FR-001…FR-005, research.md R9)."""

from __future__ import annotations

from pathlib import Path

import pytest

from printbot.core.documents import (
    DocumentError,
    detect_format,
    page_count,
    validate_size,
    validate_source,
)
from printbot.core.models import DocumentFormat, ErrorCode
from tests.conftest import make_docx_bytes, make_pdf_bytes


def write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_detects_docx_by_content(tmp_path: Path) -> None:
    assert detect_format(write(tmp_path, "a.docx", make_docx_bytes())) is DocumentFormat.DOCX


def test_detects_pdf_by_content(tmp_path: Path) -> None:
    assert detect_format(write(tmp_path, "a.pdf", make_pdf_bytes())) is DocumentFormat.PDF


def test_extension_does_not_win_over_content(tmp_path: Path) -> None:
    """Переименованный файл распознаётся по содержимому, а не по расширению."""
    assert detect_format(write(tmp_path, "trap.pdf", make_docx_bytes())) is DocumentFormat.DOCX
    assert detect_format(write(tmp_path, "trap.docx", make_pdf_bytes())) is DocumentFormat.PDF


def test_unsupported_format_rejected(tmp_path: Path) -> None:
    with pytest.raises(DocumentError) as exc:
        detect_format(write(tmp_path, "table.xlsx", b"\x89PNG\r\n\x1a\n random bytes"))
    assert exc.value.code is ErrorCode.UNSUPPORTED_FORMAT


def test_zip_without_word_document_rejected(tmp_path: Path) -> None:
    """ZIP-архив (в т.ч. xlsx) не является DOCX."""
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")
    with pytest.raises(DocumentError) as exc:
        detect_format(write(tmp_path, "book.xlsx", buffer.getvalue()))
    assert exc.value.code is ErrorCode.UNSUPPORTED_FORMAT


def test_ole_file_rejected_with_hint(tmp_path: Path) -> None:
    """Старый .doc или защищённый паролем DOCX — понятный отказ (FR-005)."""
    data = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64
    with pytest.raises(DocumentError) as exc:
        detect_format(write(tmp_path, "old.doc", data))
    assert exc.value.user_message


def test_empty_file_rejected(tmp_path: Path) -> None:
    with pytest.raises(DocumentError) as exc:
        detect_format(write(tmp_path, "empty.docx", b""))
    assert exc.value.code is ErrorCode.CORRUPT_FILE


def test_truncated_docx_rejected(tmp_path: Path) -> None:
    """Обрезанный архив (потеряно оглавление ZIP) — повреждённый файл."""
    broken = make_docx_bytes()[:-60]
    with pytest.raises(DocumentError) as exc:
        detect_format(write(tmp_path, "broken.docx", broken))
    assert exc.value.code is ErrorCode.CORRUPT_FILE


def test_docx_with_damaged_stream_rejected(tmp_path: Path) -> None:
    """Оглавление цело, но данные word/document.xml битые — ловим при чтении."""
    data = bytearray(make_docx_bytes())
    marker = data.find(b"word/document.xml")
    assert marker > 0
    start = marker + len("word/document.xml")
    data[start : start + 40] = bytes(40)
    with pytest.raises(DocumentError) as exc:
        detect_format(write(tmp_path, "broken.docx", bytes(data)))
    assert exc.value.code is ErrorCode.CORRUPT_FILE


def test_encrypted_pdf_rejected(tmp_path: Path) -> None:
    path = write(tmp_path, "secret.pdf", make_pdf_bytes(password="s3cret"))
    with pytest.raises(DocumentError) as exc:
        validate_source(path)
    assert exc.value.code is ErrorCode.ENCRYPTED_FILE


def test_validate_size_limit() -> None:
    validate_size(1024, max_bytes=2048)
    with pytest.raises(DocumentError) as exc:
        validate_size(4096, max_bytes=2048)
    assert exc.value.code is ErrorCode.FILE_TOO_LARGE


def test_validate_size_rejects_empty() -> None:
    with pytest.raises(DocumentError) as exc:
        validate_size(0, max_bytes=2048)
    assert exc.value.code is ErrorCode.CORRUPT_FILE


def test_page_count(tmp_path: Path) -> None:
    assert page_count(write(tmp_path, "three.pdf", make_pdf_bytes(pages=3))) == 3


def test_page_count_of_broken_pdf_is_none(tmp_path: Path) -> None:
    assert page_count(write(tmp_path, "broken.pdf", b"%PDF-1.4\nnot really a pdf")) is None
