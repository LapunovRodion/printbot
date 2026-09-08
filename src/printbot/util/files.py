"""Временные каталоги заданий и их гарантированная уборка (FR-028)."""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager, suppress
from pathlib import Path

log = logging.getLogger(__name__)

#: Каталоги старше этого возраста считаются осиротевшими и удаляются при уборке.
ORPHAN_AGE_SECONDS = 3600


def job_dir(root: Path, job_id: int | str) -> Path:
    return root / str(job_id)


@contextmanager
def job_workspace(root: Path, job_id: int | str) -> Iterator[Path]:
    """Каталог задания, удаляемый при любом исходе."""
    path = job_dir(root, job_id)
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        remove_tree(path)


def remove_tree(path: Path) -> None:
    with suppress(OSError):
        shutil.rmtree(path, ignore_errors=True)


def sweep_orphans(root: Path, max_age_seconds: int = ORPHAN_AGE_SECONDS) -> int:
    """Удаляет каталоги заданий старше max_age_seconds. Возвращает число удалённых."""
    if not root.exists():
        return 0
    removed = 0
    now = time.time()
    for child in root.iterdir():
        if not child.is_dir():
            continue
        try:
            age = now - child.stat().st_mtime
        except OSError:  # pragma: no cover - каталог исчез между вызовами
            continue
        if age >= max_age_seconds:
            remove_tree(child)
            removed += 1
    if removed:
        log.info("Удалено осиротевших каталогов заданий: %s", removed)
    return removed


@asynccontextmanager
async def cleanup_task(
    root: Path, interval_minutes: int, max_age_seconds: int = ORPHAN_AGE_SECONDS
) -> AsyncIterator[asyncio.Task]:
    """Фоновая периодическая уборка временных файлов."""

    async def _loop() -> None:
        while True:
            await asyncio.sleep(interval_minutes * 60)
            try:
                await asyncio.to_thread(sweep_orphans, root, max_age_seconds)
            except Exception:  # pragma: no cover - уборка не должна ронять бота
                log.exception("Ошибка фоновой уборки временных файлов")

    task = asyncio.create_task(_loop(), name="printbot-cleanup")
    try:
        yield task
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
