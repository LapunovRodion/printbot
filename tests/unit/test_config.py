"""Юнит-тесты конфигурации (contracts/configuration.md)."""

from __future__ import annotations

from pathlib import Path

import pytest

from printbot.config import ConfigError, Settings, load_printers

VALID = """
[[printer]]
key = "buh"
display_name = "Бухгалтерия"
system_name = "Pantum P5100"
"""


def write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "printers.toml"
    path.write_text(content, encoding="utf-8")
    return path


def test_loads_valid_file(tmp_path: Path) -> None:
    printers = load_printers(write(tmp_path, VALID))
    assert len(printers) == 1
    assert printers[0].key == "buh"
    assert printers[0].enabled is True
    assert printers[0].supports_duplex is None


def test_example_file_is_valid() -> None:
    printers = load_printers(Path("printers.example.toml"))
    assert {p.key for p in printers} == {"buh", "office"}


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="Не найден файл"):
        load_printers(tmp_path / "nope.toml")


def test_no_printers(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="ни одной секции"):
        load_printers(write(tmp_path, "# пусто\n"))


def test_duplicate_key(tmp_path: Path) -> None:
    content = VALID + """
[[printer]]
key = "buh"
display_name = "Другой"
system_name = "GM1033ADN"
"""
    with pytest.raises(ConfigError, match="Дублирующийся key"):
        load_printers(write(tmp_path, content))


def test_duplicate_system_name(tmp_path: Path) -> None:
    content = VALID + """
[[printer]]
key = "office"
display_name = "Другой"
system_name = "Pantum P5100"
"""
    with pytest.raises(ConfigError, match="Дублирующийся system_name"):
        load_printers(write(tmp_path, content))


def test_bad_key_characters(tmp_path: Path) -> None:
    content = VALID.replace('key = "buh"', 'key = "Бухгалтерия!"')
    with pytest.raises(ConfigError, match="callback_data"):
        load_printers(write(tmp_path, content))


def test_all_printers_disabled(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="enabled = true"):
        load_printers(write(tmp_path, VALID + "enabled = false\n"))


def test_missing_required_field(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="отсутствует обязательное поле"):
        load_printers(write(tmp_path, '[[printer]]\nkey = "buh"\n'))


def test_admin_ids_parsing() -> None:
    settings = Settings(bot_token="t", admin_ids=" 111, 222 ,", _env_file=None)
    assert settings.admin_id_set == frozenset({111, 222})


def test_admin_ids_invalid() -> None:
    settings = Settings(bot_token="t", admin_ids="111,abc", _env_file=None)
    with pytest.raises(ConfigError, match="не число"):
        _ = settings.admin_id_set


def test_unknown_print_backend() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="PRINT_BACKEND"):
        Settings(bot_token="t", admin_ids="1", print_backend="lpr", _env_file=None)


def test_max_file_mb_capped_at_bot_api_limit() -> None:
    """Лимит скачивания Bot API — 20 МБ, больше настроить нельзя."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(bot_token="t", admin_ids="1", max_file_mb=100, _env_file=None)
