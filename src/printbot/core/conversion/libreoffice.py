"""Конвертация DOCX → PDF через headless LibreOffice (research.md R2)."""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import suppress
from pathlib import Path

from printbot.core.conversion.base import ConversionError
from printbot.core.documents import PDF_SIGNATURE
from printbot.core.models import ErrorCode

log = logging.getLogger(__name__)


class LibreOfficeConverter:
    """Каждому вызову — свой профиль LibreOffice, иначе второй запуск молча ничего не делает."""

    def __init__(self, soffice_path: Path, extra_args: list[str] | None = None) -> None:
        self.soffice_path = Path(soffice_path)
        self.extra_args = list(extra_args or [])

    def build_command(self, source: Path, out_dir: Path) -> list[str]:
        profile = (out_dir / f"lo-profile-{uuid.uuid4().hex}").resolve()
        return [
            str(self.soffice_path),
            *self.extra_args,
            "--headless",
            "--norestore",
            "--nolockcheck",
            "--nodefault",
            f"-env:UserInstallation={profile.as_uri()}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(out_dir),
            str(source),
        ]

    async def to_pdf(self, source: Path, out_dir: Path, timeout_s: float) -> Path:
        source = Path(source)
        if source.read_bytes()[: len(PDF_SIGNATURE)] == PDF_SIGNATURE:
            return source

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        command = self.build_command(source, out_dir)
        log.debug("Конвертация: %s", " ".join(command))

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as exc:
            raise ConversionError(
                ErrorCode.CONVERSION_FAILED, f"не удалось запустить {self.soffice_path}: {exc}"
            ) from exc

        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=timeout_s)
        except TimeoutError as exc:
            await _terminate(process)
            raise ConversionError(
                ErrorCode.TIMEOUT, f"конвертация не уложилась в {timeout_s} с"
            ) from exc

        if process.returncode != 0:
            tail = (stdout or b"").decode("utf-8", "replace")[-500:]
            raise ConversionError(
                ErrorCode.CONVERSION_FAILED, f"soffice код {process.returncode}: {tail}"
            )

        result = out_dir / f"{source.stem}.pdf"
        if not result.exists():
            candidates = sorted(out_dir.glob("*.pdf"))
            if not candidates:
                raise ConversionError(ErrorCode.CONVERSION_FAILED, "PDF не появился в каталоге")
            result = candidates[0]
        if result.stat().st_size == 0:
            raise ConversionError(ErrorCode.CONVERSION_FAILED, "получен пустой PDF")
        return result


async def _terminate(process: asyncio.subprocess.Process) -> None:
    """Гарантированно завершает зависший процесс, не оставляя сирот."""
    with suppress(ProcessLookupError):
        process.kill()
    with suppress(Exception):
        await asyncio.wait_for(process.wait(), timeout=5)
