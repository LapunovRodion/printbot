# Implementation Plan: Telegram-бот печати документов

**Branch**: `001-telegram-print-bot` | **Date**: 2026-09-08 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-telegram-print-bot/spec.md`

## Summary

Долгоживущее Python-приложение на хосте Windows: Telegram-бот принимает от авторизованных пользователей DOCX/PDF, спрашивает принтер (если их больше одного), режим сторон и количество копий, после подтверждения ставит задание в очередь и печатает.

Технический подход: `aiogram 3.x` (long polling, FSM для диалога оформления, middleware для авторизации) + слой заданий на `asyncio` с отдельной очередью и воркером на каждый принтер (гарантирует последовательность и отсутствие перемешивания страниц) + слой печати, скрытый за интерфейсом `PrinterBackend`. Реальная реализация бэкенда на Windows: DOCX → PDF через headless LibreOffice, печать PDF через SumatraPDF CLI (умеет дуплекс и число копий одной командой), статус и поддержка дуплекса — через `win32print`. Состояние (пользователи, задания, журнал, код доступа) — в SQLite, что даёт восстановление после перезапуска и бессрочный журнал. Тестируемость обеспечивается подменой бэкенда печати и конвертера на фейковые реализации.

## Technical Context

**Language/Version**: Python 3.12 (минимум 3.11 — требование aiogram 3.x)

**Primary Dependencies**: `aiogram ~=3.x` (Telegram Bot API), `aiosqlite` (асинхронный SQLite), `pypdf` (число страниц, проверка шифрования PDF), `pywin32` (перечисление принтеров, статус, определение дуплекса), `pydantic-settings` (конфигурация). Внешние утилиты на хосте: **LibreOffice** (`soffice.exe`, конвертация DOCX→PDF) и **SumatraPDF** (`SumatraPDF.exe`, печать PDF с параметрами)

**Storage**: SQLite (файл `data/printbot.db`, режим WAL). Таблицы: `users`, `print_jobs`, `settings` (в т.ч. хеш кода доступа), `audit_events`. Документы на диске не хранятся — только временные файлы задания

**Testing**: `pytest` + `pytest-asyncio`; фейковые `PrinterBackend` и `DocumentConverter` для юнит- и интеграционных тестов; тесты handlers через прямой вызов с подставными `Message`/`FSMContext`

**Target Platform**: Windows 10/11 (x64), рабочий компьютер офиса; процесс запускается в пользовательской сессии (Task Scheduler, «При входе в систему», перезапуск при сбое) — так видны сетевые принтеры, подключённые под этим пользователем

**Project Type**: Single project — одно долгоживущее консольное приложение (бот + фоновые воркеры печати)

**Performance Goals**: реакция бота на сообщение < 2 с; задание ≤10 страниц уходит в спулер принтера < 60 с после подтверждения (SC-002); одновременное обслуживание нескольких пользователей без блокировки цикла событий

**Constraints**: файлы ≤ 20 МБ (лимит скачивания Bot API); работа без присмотра, автовосстановление после потери сети и после перезапуска (FR-019, FR-029); временные файлы удаляются ≤ 10 минут после завершения задания (FR-028, SC-007); интерфейс на русском

**Scale/Scope**: до нескольких десятков пользователей, сотни заданий в месяц, 2 принтера на старте с расчётом на ~10; журнал хранится бессрочно (FR-027)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Файл `.specify/memory/constitution.md` присутствует, но содержит **незаполненный шаблон** — ратифицированных принципов проекта нет. Проектных гейтов, которые можно нарушить, не существует; вместо них применяются базовые инженерные критерии:

| Гейт | Статус (до Phase 0) | Статус (после Phase 1) | Комментарий |
|------|---------------------|------------------------|-------------|
| Простота: минимум слоёв и зависимостей под задачу | PASS | PASS | Один проект, без веб-фреймворка и внешней СУБД; 5 прикладных зависимостей |
| Тестируемость: бизнес-логика проверяема без физического принтера | PASS | PASS | `PrinterBackend` и `DocumentConverter` — протоколы с фейковыми реализациями |
| Границы: платформенный код изолирован | PASS | PASS | Всё Windows-специфичное только в `core/printing/windows.py` |
| Наблюдаемость: причина любого отказа доступна пользователю и в журнале | PASS | PASS | Единая таксономия ошибок (см. contracts/printer-backend.md), запись в `print_jobs.error_code` |
| Безопасность: секреты не в коде, код доступа не хранится в открытом виде | PASS | PASS | Токен и путь к БД — из окружения; код доступа — `scrypt`-хеш с солью |
| Отсутствие неоправданной сложности | PASS | PASS | Раздел Complexity Tracking пуст |

**Рекомендация**: заполнить конституцию через `/speckit-constitution` — тогда последующие фичи будут проверяться по реальным принципам проекта, а не по этим умолчаниям.

## Project Structure

### Documentation (this feature)

```text
specs/001-telegram-print-bot/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
│   ├── bot-interaction.md
│   ├── printer-backend.md
│   └── configuration.md
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/printbot/
├── __main__.py               # точка входа: конфиг, БД, бэкенды, запуск бота и воркеров
├── config.py                 # загрузка и валидация настроек (.env + printers.toml)
├── texts.py                  # все русские строки интерфейса в одном месте
├── bot/
│   ├── dispatcher.py         # сборка Dispatcher, роутеров, middlewares
│   ├── states.py             # FSM: PrintFlow (waiting_printer/duplex/copies/confirm), AuthFlow
│   ├── keyboards.py          # инлайн-клавиатуры и схема callback_data
│   ├── middlewares/
│   │   ├── auth.py           # FR-020..FR-021: пропускает только авторизованных
│   │   └── errors.py         # единый обработчик исключений → понятное сообщение
│   └── routers/
│       ├── common.py         # /start, /help, /cancel, таймаут диалога
│       ├── auth.py           # US3: ввод кода доступа, блокировка при переборе
│       ├── printing.py       # US1, US2: приём файла → параметры → подтверждение
│       └── admin.py          # US5: журнал, смена кода, отзыв доступа, список принтеров
├── core/
│   ├── models.py             # доменные модели и перечисления (JobStatus, DuplexMode, ...)
│   ├── documents.py          # определение формата по сигнатуре, валидация, число страниц
│   ├── jobs.py               # JobService: очередь на принтер, воркеры, статусы, уведомления
│   ├── access.py             # AccessService: хеш кода, проверка, счётчик попыток, блокировка
│   ├── printers.py           # PrinterRegistry: список принтеров, доступность, дуплекс
│   ├── conversion/
│   │   ├── base.py           # DocumentConverter (Protocol)
│   │   ├── libreoffice.py    # конвертация DOCX→PDF через soffice
│   │   └── fake.py           # для тестов
│   └── printing/
│       ├── base.py           # PrinterBackend (Protocol), PrintOptions, PrintError
│       ├── windows.py        # SumatraPDF + win32print
│       └── fake.py           # для тестов
├── storage/
│   ├── db.py                 # подключение, миграции схемы, WAL
│   ├── users.py              # репозиторий пользователей и доступа
│   ├── jobs.py               # репозиторий заданий и журнала
│   └── settings.py           # репозиторий настроек (код доступа и пр.)
└── util/
    ├── files.py              # временные каталоги задания, гарантированная очистка
    └── logging.py            # ротация логов на диск

tests/
├── contract/                 # соответствие реализаций протоколам PrinterBackend/Converter
├── integration/              # сквозной путь: файл → параметры → очередь → фейковая печать
└── unit/                     # documents, access, jobs, keyboards, config
```

**Structure Decision**: Single project (Option 1) — одно приложение без разделения на фронтенд/бэкенд: интерфейсом служит сам Telegram. Разделение по слоям вместо технических папок `models/services/lib`: `bot/` (транспорт и диалоги), `core/` (доменная логика и платформенные адаптеры), `storage/` (персистентность). Всё, что зависит от Windows и внешних утилит, сосредоточено в `core/printing/windows.py` и `core/conversion/libreoffice.py` — только эти два модуля требуют реального хоста, остальное покрывается тестами на любой машине.

## Complexity Tracking

> Нарушений Constitution Check нет — раздел не заполняется.
