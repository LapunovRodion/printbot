"""Композиционный корень: все сервисы, доступные хендлерам через workflow_data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import aiosqlite

from printbot.config import AppConfig
from printbot.core.access import AccessService
from printbot.core.jobs import JobService
from printbot.core.printers import PrinterRegistry
from printbot.storage.jobs import JobRepository
from printbot.storage.settings import SettingsRepository
from printbot.storage.users import UserRepository


@dataclass(slots=True)
class Services:
    config: AppConfig
    conn: aiosqlite.Connection
    users: UserRepository
    jobs: JobRepository
    settings: SettingsRepository
    access: AccessService
    printers: PrinterRegistry
    job_service: JobService
    jobs_root: Path

    @property
    def admin_ids(self) -> frozenset[int]:
        return self.config.settings.admin_id_set

    def is_admin(self, telegram_id: int) -> bool:
        return telegram_id in self.admin_ids
