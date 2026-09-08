# Contract: внутренние интерфейсы печати и конвертации

**Дата**: 2026-09-08 | Назначение: изолировать всё платформозависимое, чтобы логика тестировалась без принтера (plan.md § Constitution Check → «Тестируемость»).

## `DocumentConverter` (Protocol)

```python
class DocumentConverter(Protocol):
    async def to_pdf(self, source: Path, out_dir: Path, timeout_s: float) -> Path:
        """Возвращает путь к PDF. Для входного PDF — возвращает его же без изменений.
        Бросает ConversionError(ErrorCode.CONVERSION_FAILED | CORRUPT_FILE | TIMEOUT)."""
```

| Реализация | Модуль | Механика |
|---|---|---|
| `LibreOfficeConverter` | `core/conversion/libreoffice.py` | `soffice.exe --headless --norestore -env:UserInstallation=file:///<профиль задания> --convert-to pdf --outdir <out_dir> <source>` |
| `FakeConverter` | `core/conversion/fake.py` | Копирует заранее подготовленный PDF; умеет по флагу бросать любую `ConversionError` |

**Контрактные обязательства (проверяются тестами в `tests/contract/`)**
1. Результат — существующий непустой файл в `out_dir`; исходный файл не изменяется.
2. Превышение `timeout_s` → процесс завершается принудительно, бросается `TIMEOUT`; зависших процессов не остаётся.
3. Профиль LibreOffice уникален на вызов — два одновременных вызова корректны (research.md R2).
4. Вход в формате PDF возвращается без перекодирования.

## `PrinterBackend` (Protocol)

```python
class PrinterBackend(Protocol):
    async def list_printers(self) -> list[PrinterInfo]: ...
    async def get_status(self, system_name: str) -> PrinterStatus: ...
    async def print_pdf(self, pdf: Path, options: PrintOptions, timeout_s: float) -> None:
        """Успех = задание принято спулером принтера.
        Бросает PrintError(ErrorCode.PRINTER_OFFLINE | PAPER_OUT | PAPER_JAM | NO_TONER |
                           PRINTER_ERROR | TIMEOUT | INTERNAL)."""
```

```python
@dataclass(frozen=True)
class PrintOptions:
    system_name: str          # точное имя принтера в системе
    duplex: DuplexMode        # SIMPLEX | DUPLEX_LONG
    copies: int               # 1..50, валидируется до вызова
    paper: PaperSize = PaperSize.A4
    monochrome: bool = True

@dataclass(frozen=True)
class PrinterInfo:
    system_name: str
    supports_duplex: bool
    supports_a3: bool

@dataclass(frozen=True)
class PrinterStatus:
    available: bool
    reason: ErrorCode | None   # причина недоступности
    queued_jobs: int
```

| Реализация | Модуль | Механика |
|---|---|---|
| `WindowsPrinterBackend` | `core/printing/windows.py` | Печать: `SumatraPDF.exe -print-to "<system_name>" -print-settings "<duplexlong\|simplex>,<N>x,paper=<A4\|A3>,monochrome" -silent -exit-when-done <pdf>`. Список и статус: `win32print.EnumPrinters`, `GetPrinter(handle, 2)`, `DeviceCapabilities(..., DC_DUPLEX=7)` с запасным путём через `DM_DUPLEX` в DEVMODE, форматы бумаги — `DeviceCapabilities(..., DC_PAPERS=2)` и поиск `DMPAPER_A3=8` |
| `FakePrinterBackend` | `core/printing/fake.py` | Складывает «напечатанное» в каталог, ведёт список вызовов, по сценарию возвращает любую `PrintError` |

**Контрактные обязательства (проверяются тестами в `tests/contract/`)**
1. `print_pdf` возвращает управление только после завершения внешнего процесса; ненулевой код возврата → `PrintError`, а не молчаливый успех.
2. `copies` и `duplex` передаются устройству ровно один раз — дублирование копий (например, цикл по копиям поверх флага `Nx`) запрещено.
3. `DUPLEX_LONG` не передаётся принтеру с `supports_duplex = false`, `PaperSize.A3` — принтеру с `supports_a3 = false`; такой вызов есть ошибка вызывающего кода (`INTERNAL`).
4. `list_printers` не бросает исключение при недоступном принтере — недоступность выражается через `get_status`.
5. Любой отказ отображается в один из кодов `ErrorCode` — «сырые» исключения наружу не выходят.

## Соответствие статусов Windows кодам ошибок

| Флаг `win32print` | `ErrorCode` | Текст пользователю (смысл) |
|---|---|---|
| `PRINTER_STATUS_OFFLINE`, `PRINTER_ATTRIBUTE_WORK_OFFLINE` | `PRINTER_OFFLINE` | Принтер выключен или недоступен по сети |
| `PRINTER_STATUS_PAPER_OUT`, `PAPER_PROBLEM` | `PAPER_OUT` | В принтере закончилась бумага |
| `PRINTER_STATUS_PAPER_JAM` | `PAPER_JAM` | Замятие бумаги |
| `PRINTER_STATUS_NO_TONER`, `TONER_LOW` | `NO_TONER` | Закончился тонер |
| `PRINTER_STATUS_ERROR`, `PRINTER_STATUS_PAUSED`, прочее | `PRINTER_ERROR` | Принтер сообщает об ошибке |
| Превышен таймаут печати | `TIMEOUT` | Принтер не ответил вовремя |

## Запасной путь печати

Если у конкретной модели SumatraPDF не отрабатывает дуплекс, вводится второй `PrinterBackend` на Ghostscript
(`gswin64c -dPrinted -dBatch -dNOPAUSE -dNumCopies=N -sDEVICE=mswinpr2 -sOutputFile="%printer%<имя>"`)
без изменения вызывающего кода — выбор бэкенда задаётся настройкой `PRINT_BACKEND` (см. configuration.md).
