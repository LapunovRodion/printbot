"""Точка входа: сборка сервисов, восстановление после перезапуска, polling."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from printbot.bot.dispatcher import create_dispatcher
from printbot.config import AppConfig, ConfigError, load_config
from printbot.core.access import AccessService
from printbot.core.conversion.base import DocumentConverter
from printbot.core.conversion.fake import FakeConverter
from printbot.core.conversion.libreoffice import LibreOfficeConverter
from printbot.core.jobs import JobService
from printbot.core.printers import PrinterRegistry
from printbot.core.printing.base import PrinterBackend
from printbot.core.printing.fake import FakePrinterBackend
from printbot.core.printing.windows import WindowsPrinterBackend
from printbot.services import Services
from printbot.storage.db import connect
from printbot.storage.jobs import JobRepository
from printbot.storage.settings import SettingsRepository
from printbot.storage.users import UserRepository
from printbot.util.files import cleanup_task, sweep_orphans
from printbot.util.logging import redactor, setup_logging

log = logging.getLogger("printbot")


def build_backends(config: AppConfig) -> tuple[PrinterBackend, DocumentConverter]:
    settings = config.settings
    if settings.print_backend == "fake":
        backend: PrinterBackend = FakePrinterBackend(
            output_dir=settings.resolved_jobs_dir() / "_printed",
            printers={p.system_name: True for p in config.enabled_printers},
        )
        converter: DocumentConverter = FakeConverter()
        log.warning("PRINT_BACKEND=fake — печать имитируется, файлы складываются в каталог")
        return backend, converter

    if settings.print_backend == "ghostscript":
        # Запасной путь описан в research.md R3; пока используется тот же интерфейс.
        log.warning("PRINT_BACKEND=ghostscript пока не реализован, используется SumatraPDF")

    return (
        WindowsPrinterBackend(sumatra_path=settings.sumatra_path),
        LibreOfficeConverter(soffice_path=settings.soffice_path),
    )


async def build_services(config: AppConfig, bot: Bot | None) -> Services:
    settings = config.settings
    conn = await connect(settings.db_path)
    users = UserRepository(conn)
    jobs = JobRepository(conn)
    settings_repo = SettingsRepository(conn)

    access = AccessService(
        users,
        settings_repo,
        jobs,
        attempts_limit=settings.lockout_attempts,
        lockout_minutes=settings.lockout_minutes,
    )
    backend, converter = build_backends(config)
    printers = PrinterRegistry(config.printers, backend)

    async def notifier(chat_id: int, text: str) -> None:
        if bot is not None:
            await bot.send_message(chat_id, text)

    job_service = JobService(
        jobs,
        converter,
        backend,
        convert_timeout_s=settings.convert_timeout_s,
        print_timeout_s=settings.print_timeout_s,
        notifier=notifier,
    )
    return Services(
        config=config,
        conn=conn,
        users=users,
        jobs=jobs,
        settings=settings_repo,
        access=access,
        printers=printers,
        job_service=job_service,
        jobs_root=settings.resolved_jobs_dir(),
    )


async def main() -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"Конфигурация некорректна: {exc}", file=sys.stderr)
        return 2

    settings = config.settings
    setup_logging(settings.log_level, Path(settings.log_file))
    redactor.add_secret(settings.bot_token)

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    services = await build_services(config, bot)

    new_code = await services.access.ensure_code()
    if new_code:
        redactor.add_secret(new_code)
        print("=" * 60)
        print(f"  Сгенерирован код доступа: {new_code}")
        print("  Он показывается один раз. Сменить: команда /setcode в боте.")
        print("=" * 60)

    jobs_root = services.jobs_root
    jobs_root.mkdir(parents=True, exist_ok=True)
    sweep_orphans(jobs_root)

    await services.printers.verify_at_startup()
    for view in await services.printers.views():
        log.info(
            "Принтер «%s» (%s): %s, дуплекс: %s",
            view.display_name,
            view.system_name,
            "доступен" if view.available else "недоступен",
            "да" if view.supports_duplex else "нет",
        )

    await services.job_service.start(services.printers.system_names)
    await services.job_service.recover_unfinished()

    dispatcher = create_dispatcher(services)
    log.info("Бот запущен, ожидает сообщения")
    try:
        async with cleanup_task(jobs_root, settings.cleanup_interval_min):
            await dispatcher.start_polling(bot, handle_signals=True)
    finally:
        await services.job_service.stop()
        await services.conn.close()
        await bot.session.close()
        log.info("Бот остановлен")
    return 0


def run() -> None:
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:  # pragma: no cover - ручная остановка
        raise SystemExit(0) from None


if __name__ == "__main__":
    run()
