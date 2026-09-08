"""Фейковый конвертер для тестов."""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from printbot.core.conversion.base import ConversionError
from printbot.core.models import ErrorCode

#: Минимальный валидный одностраничный PDF.
MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)


@dataclass
class FakeConverter:
    """Возвращает PDF как есть, иначе кладёт заранее подготовленный PDF."""

    fail_with: ErrorCode | None = None
    template_pdf: bytes = MINIMAL_PDF
    converted: list[Path] = field(default_factory=list)

    async def to_pdf(self, source: Path, out_dir: Path, timeout_s: float) -> Path:
        if self.fail_with is not None:
            raise ConversionError(self.fail_with, "сценарий теста")
        if source.suffix.lower() == ".pdf" or source.read_bytes()[:5] == b"%PDF-":
            return source
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{source.stem}.pdf"
        if self.template_pdf:
            target.write_bytes(self.template_pdf)
        else:  # pragma: no cover - запасной путь
            shutil.copyfile(source, target)
        self.converted.append(target)
        return target
