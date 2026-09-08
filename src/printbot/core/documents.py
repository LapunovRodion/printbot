"""Определение формата, валидация документов и подсчёт страниц (FR-001…FR-005)."""

from __future__ import annotations

import logging
import zipfile
import zlib
from pathlib import Path

from printbot.core.models import DocumentFormat, ErrorCode

log = logging.getLogger(__name__)

PDF_SIGNATURE = b"%PDF-"
ZIP_SIGNATURE = b"PK\x03\x04"
OLE_SIGNATURE = b"\xd0\xcf\x11\xe0"

_DOCX_REQUIRED = "word/document.xml"


class DocumentError(RuntimeError):
    """Документ не может быть напечатан; code — из общей таксономии."""

    def __init__(self, code: ErrorCode, detail: str = "", user_message: str | None = None) -> None:
        super().__init__(f"{code}: {detail}" if detail else str(code))
        self.code = code
        self.detail = detail
        self.user_message = user_message


def validate_size(size_bytes: int | None, max_bytes: int) -> None:
    """Проверка размера до скачивания файла (FR-004)."""
    if not size_bytes:
        raise DocumentError(ErrorCode.CORRUPT_FILE, "файл пуст")
    if size_bytes > max_bytes:
        raise DocumentError(
            ErrorCode.FILE_TOO_LARGE, f"{size_bytes} B > {max_bytes} B"
        )


def detect_format(path: Path) -> DocumentFormat:
    """Определяет формат по содержимому файла, а не по расширению (research.md R9)."""
    try:
        with path.open("rb") as handle:
            head = handle.read(8)
    except OSError as exc:
        raise DocumentError(ErrorCode.CORRUPT_FILE, str(exc)) from exc

    if not head:
        raise DocumentError(ErrorCode.CORRUPT_FILE, "файл пуст")

    if head.startswith(PDF_SIGNATURE):
        return DocumentFormat.PDF

    if head.startswith(OLE_SIGNATURE):
        raise DocumentError(
            ErrorCode.UNSUPPORTED_FORMAT,
            "OLE-контейнер (.doc или защищённый паролем DOCX)",
            user_message=(
                "Это старый формат .doc или файл защищён паролем. "
                "Пересохраните документ в .docx (или снимите пароль) и пришлите снова."
            ),
        )

    if head.startswith(ZIP_SIGNATURE):
        return _detect_zip_format(path)

    raise DocumentError(ErrorCode.UNSUPPORTED_FORMAT, f"неизвестная сигнатура: {head[:4]!r}")


def _detect_zip_format(path: Path) -> DocumentFormat:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if _DOCX_REQUIRED not in names:
                raise DocumentError(
                    ErrorCode.UNSUPPORTED_FORMAT, "ZIP без word/document.xml — это не DOCX"
                )
            # Читаем содержимое: битый архив с целым оглавлением иначе выглядит валидным.
            archive.read(_DOCX_REQUIRED)
    except DocumentError:
        raise
    except (zipfile.BadZipFile, zlib.error, EOFError, OSError, ValueError) as exc:
        # Битый поток внутри архива приходит как zlib.error/EOFError, а не BadZipFile.
        raise DocumentError(ErrorCode.CORRUPT_FILE, f"повреждённый DOCX: {exc}") from exc
    return DocumentFormat.DOCX


def validate_source(path: Path) -> DocumentFormat:
    """Полная проверка скачанного файла: формат + отсутствие пароля (FR-005)."""
    fmt = detect_format(path)
    if fmt is DocumentFormat.PDF and _is_encrypted_pdf(path):
        raise DocumentError(ErrorCode.ENCRYPTED_FILE, "PDF защищён паролем")
    return fmt


def _is_encrypted_pdf(path: Path) -> bool:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        return bool(PdfReader(str(path)).is_encrypted)
    except (PdfReadError, OSError, ValueError) as exc:
        raise DocumentError(ErrorCode.CORRUPT_FILE, f"PDF не читается: {exc}") from exc


def page_count(pdf_path: Path) -> int | None:
    """Число страниц готового PDF; None, если посчитать не удалось (research.md R9)."""
    from pypdf import PdfReader

    try:
        return len(PdfReader(str(pdf_path)).pages)
    except Exception as exc:  # pypdf бросает разнородные ошибки на битых файлах
        log.warning("Не удалось посчитать страницы в %s: %s", pdf_path, exc)
        return None


def estimate_pages(path: Path, fmt: DocumentFormat) -> int | None:
    """Оценка числа страниц до печати.

    Для PDF значение точное. Для DOCX берётся подсказка ``docProps/app.xml``, которую
    записывают Word и LibreOffice; если её нет — возвращается None и предупреждение
    об объёме не показывается (точное число появится после конвертации).
    """
    if fmt is DocumentFormat.PDF:
        return page_count(path)
    return _docx_page_hint(path)


def _docx_page_hint(path: Path) -> int | None:
    import re

    try:
        with zipfile.ZipFile(path) as archive:
            if "docProps/app.xml" not in archive.namelist():
                return None
            raw = archive.read("docProps/app.xml").decode("utf-8", "replace")
    except (zipfile.BadZipFile, zlib.error, EOFError, OSError, ValueError):
        return None
    match = re.search(r"<Pages>(\d+)</Pages>", raw)
    if not match:
        return None
    pages = int(match.group(1))
    return pages if pages > 0 else None
