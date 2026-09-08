"""Общие фикстуры тестов."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from printbot.config import AppConfig, Settings
from printbot.core.conversion.fake import MINIMAL_PDF, FakeConverter
from printbot.core.models import PrinterConfig
from printbot.core.printing.fake import FakePrinterBackend
from printbot.storage.db import connect
from printbot.storage.jobs import JobRepository
from printbot.storage.settings import SettingsRepository
from printbot.storage.users import UserRepository

PRINTER_A = PrinterConfig(
    key="buh", display_name="Бухгалтерия", system_name="Pantum P5100", model="Pantum 5100"
)
PRINTER_B = PrinterConfig(
    key="office", display_name="Кабинет", system_name="GM1033ADN", model="GM1033ADN"
)


def make_docx_bytes(text: str = "Тестовый документ") -> bytes:
    """Минимальный валидный по структуре DOCX (ZIP с нужными записями)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
            'package/2006/content-types"/>',
        )
        archive.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships/>')
        archive.writestr(
            "word/document.xml",
            f'<?xml version="1.0"?><w:document><w:body><w:p><w:r><w:t>{text}</w:t>'
            "</w:r></w:p></w:body></w:document>",
        )
    return buffer.getvalue()


def make_pdf_bytes(pages: int = 1, password: str | None = None) -> bytes:
    """Настоящий PDF с заданным числом страниц, при необходимости зашифрованный."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595, height=842)
    if password is not None:
        writer.encrypt(password)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.fixture
def docx_bytes() -> bytes:
    return make_docx_bytes()


@pytest.fixture
def pdf_bytes() -> bytes:
    return make_pdf_bytes()


@pytest.fixture
async def db(tmp_path: Path):
    conn = await connect(tmp_path / "test.db")
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def users_repo(db) -> UserRepository:
    return UserRepository(db)


@pytest.fixture
async def jobs_repo(db) -> JobRepository:
    return JobRepository(db)


@pytest.fixture
async def settings_repo(db) -> SettingsRepository:
    return SettingsRepository(db)


@pytest.fixture
def fake_printer(tmp_path: Path) -> FakePrinterBackend:
    return FakePrinterBackend(
        output_dir=tmp_path / "printed",
        printers={PRINTER_A.system_name: True, PRINTER_B.system_name: True},
    )


@pytest.fixture
def fake_converter() -> FakeConverter:
    return FakeConverter(template_pdf=MINIMAL_PDF)


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        bot_token="123456:TEST-TOKEN-FOR-TESTS-0000000000000",
        admin_ids="777",
        db_path=tmp_path / "printbot.db",
        jobs_dir=tmp_path / "jobs",
        print_backend="fake",
        log_file=tmp_path / "printbot.log",
        _env_file=None,
    )


@pytest.fixture
def app_config(test_settings: Settings) -> AppConfig:
    return AppConfig(settings=test_settings, printers=(PRINTER_A, PRINTER_B))


@pytest.fixture
def stub_bot():
    from tests.support import StubBot

    return StubBot()


@pytest.fixture
def make_services(db, test_settings, fake_printer, fake_converter, stub_bot, tmp_path: Path):
    """Фабрика контейнера сервисов с фейковыми бэкендами."""
    from printbot.config import AppConfig
    from printbot.core.access import AccessService
    from printbot.core.jobs import JobService
    from printbot.core.printers import PrinterRegistry
    from printbot.services import Services

    def factory(printers=(PRINTER_A,), backend=None, converter=None) -> Services:
        backend = backend or fake_printer
        converter = converter or fake_converter
        config = AppConfig(settings=test_settings, printers=tuple(printers))
        users = UserRepository(db)
        jobs = JobRepository(db)
        settings_repo = SettingsRepository(db)
        access = AccessService(
            users,
            settings_repo,
            jobs,
            attempts_limit=test_settings.lockout_attempts,
            lockout_minutes=test_settings.lockout_minutes,
        )
        registry = PrinterRegistry(config.printers, backend, cache_ttl=0.0)
        job_service = JobService(
            jobs,
            converter,
            backend,
            convert_timeout_s=5,
            print_timeout_s=5,
            notifier=stub_bot.send_message,
        )
        jobs_root = tmp_path / "jobs"
        jobs_root.mkdir(parents=True, exist_ok=True)
        return Services(
            config=config,
            conn=db,
            users=users,
            jobs=jobs,
            settings=settings_repo,
            access=access,
            printers=registry,
            job_service=job_service,
            jobs_root=jobs_root,
        )

    return factory


@pytest.fixture
def services(make_services):
    """Контейнер с одним принтером — шаг выбора принтера пропускается."""
    return make_services()
