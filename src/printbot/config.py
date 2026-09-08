"""Загрузка и валидация конфигурации (contracts/configuration.md)."""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from printbot.core.models import PrinterConfig

DEFAULT_PRINTERS_FILE = Path("printers.toml")
_KEY_ALLOWED = set("abcdefghijklmnopqrstuvwxyz0123456789_")


class ConfigError(RuntimeError):
    """Конфигурация некорректна — приложение не должно стартовать."""


class Settings(BaseSettings):
    """Переменные из .env / окружения."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    bot_token: str = ""
    admin_ids: str = ""

    db_path: Path = Path("data/printbot.db")
    jobs_dir: Path | None = None
    soffice_path: Path = Path(r"C:\Program Files\LibreOffice\program\soffice.exe")
    sumatra_path: Path = Path(r"tools\SumatraPDF.exe")
    ghostscript_path: Path | None = None

    print_backend: str = "sumatra"

    max_file_mb: int = Field(default=20, ge=1, le=20)
    max_copies: int = Field(default=50, ge=1, le=999)
    large_doc_pages: int = Field(default=20, ge=1)
    dialog_timeout_min: int = Field(default=15, ge=1)

    lockout_attempts: int = Field(default=5, ge=1)
    lockout_minutes: int = Field(default=15, ge=1)

    convert_timeout_s: float = Field(default=120.0, gt=0)
    print_timeout_s: float = Field(default=180.0, gt=0)
    cleanup_interval_min: int = Field(default=10, ge=1)

    log_level: str = "INFO"
    log_file: Path = Path("logs/printbot.log")
    printers_file: Path = DEFAULT_PRINTERS_FILE

    @field_validator("print_backend")
    @classmethod
    def _check_backend(cls, value: str) -> str:
        allowed = {"sumatra", "ghostscript", "fake"}
        value = value.strip().lower()
        if value not in allowed:
            raise ValueError(
                f"PRINT_BACKEND должен быть одним из {sorted(allowed)}, получено {value!r}"
            )
        return value

    @field_validator("jobs_dir", "ghostscript_path", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def admin_id_set(self) -> frozenset[int]:
        ids: set[int] = set()
        for chunk in self.admin_ids.replace(";", ",").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                ids.add(int(chunk))
            except ValueError as exc:
                raise ConfigError(f"ADMIN_IDS содержит не число: {chunk!r}") from exc
        return frozenset(ids)

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024

    def resolved_jobs_dir(self) -> Path:
        if self.jobs_dir is not None:
            return self.jobs_dir
        if sys.platform == "win32":
            base = os.environ.get("LOCALAPPDATA") or str(Path.home())
            return Path(base) / "printbot" / "jobs"
        return Path("data") / "jobs"


@dataclass(frozen=True, slots=True)
class AppConfig:
    settings: Settings
    printers: tuple[PrinterConfig, ...]

    @property
    def enabled_printers(self) -> tuple[PrinterConfig, ...]:
        return tuple(p for p in self.printers if p.enabled)


def load_printers(path: Path) -> tuple[PrinterConfig, ...]:
    """Читает и валидирует printers.toml (contracts/configuration.md)."""
    if not path.exists():
        raise ConfigError(
            f"Не найден файл со списком принтеров: {path}. "
            "Скопируйте printers.example.toml в printers.toml и укажите свои принтеры."
        )
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"Файл {path} не разбирается как TOML: {exc}") from exc

    entries = raw.get("printer")
    if not isinstance(entries, list) or not entries:
        raise ConfigError(f"В {path} нет ни одной секции [[printer]]")

    printers: list[PrinterConfig] = []
    seen_keys: set[str] = set()
    seen_names: set[str] = set()
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, dict):
            raise ConfigError(f"Секция [[printer]] №{index} в {path} задана неверно")
        try:
            key = str(entry["key"]).strip()
            display_name = str(entry["display_name"]).strip()
            system_name = str(entry["system_name"]).strip()
        except KeyError as exc:
            raise ConfigError(
                f"В секции [[printer]] №{index} отсутствует обязательное поле {exc.args[0]!r}"
            ) from exc

        if not key or len(key) > 16 or not set(key) <= _KEY_ALLOWED:
            raise ConfigError(
                f"key={key!r}: допустимы 1-16 символов из [a-z0-9_] (нужно для callback_data)"
            )
        if key in seen_keys:
            raise ConfigError(f"Дублирующийся key принтера: {key!r}")
        if system_name in seen_names:
            raise ConfigError(f"Дублирующийся system_name принтера: {system_name!r}")
        if not display_name or not system_name:
            raise ConfigError(f"Пустое display_name или system_name у принтера {key!r}")
        seen_keys.add(key)
        seen_names.add(system_name)

        supports_duplex = entry.get("supports_duplex")
        if supports_duplex is not None and not isinstance(supports_duplex, bool):
            raise ConfigError(f"supports_duplex у принтера {key!r} должен быть true/false")

        printers.append(
            PrinterConfig(
                key=key,
                display_name=display_name,
                system_name=system_name,
                model=str(entry.get("model", "")),
                enabled=bool(entry.get("enabled", True)),
                supports_duplex=supports_duplex,
            )
        )

    if not any(p.enabled for p in printers):
        raise ConfigError(f"В {path} нет ни одного принтера с enabled = true")
    return tuple(printers)


def load_config(env_file: Path | None = None, printers_file: Path | None = None) -> AppConfig:
    """Полная загрузка конфигурации с валидацией. Бросает ConfigError."""
    try:
        settings = Settings(_env_file=env_file) if env_file else Settings()
    except Exception as exc:  # pydantic ValidationError
        raise ConfigError(f"Некорректные настройки окружения: {exc}") from exc

    if not settings.bot_token.strip():
        raise ConfigError("Не задан BOT_TOKEN — возьмите токен у @BotFather и укажите в .env")
    if not settings.admin_id_set:
        raise ConfigError("Не задан ADMIN_IDS — укажите Telegram ID администраторов через запятую")
    if settings.print_backend == "ghostscript" and settings.ghostscript_path is None:
        raise ConfigError("PRINT_BACKEND=ghostscript требует указать GHOSTSCRIPT_PATH")

    printers = load_printers(printers_file or settings.printers_file)
    return AppConfig(settings=settings, printers=printers)
