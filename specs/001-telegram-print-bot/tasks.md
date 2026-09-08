---

description: "Task list template for feature implementation"
---

# Tasks: Telegram-бот печати документов

**Input**: Design documents from `/specs/001-telegram-print-bot/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Тестовые задачи включены — plan.md фиксирует `pytest` + `pytest-asyncio`, а contracts/printer-backend.md прямо требует контрактных тестов в `tests/contract/`. Тесты позволяют проверять почти весь функционал без принтера и без Windows.

**Organization**: Задачи сгруппированы по пользовательским историям спеки, чтобы каждую можно было довести и проверить независимо.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Можно выполнять параллельно (разные файлы, нет зависимостей)
- **[Story]**: К какой истории относится задача (US1…US5)
- Пути к файлам указаны точно

## Path Conventions

Single project по plan.md: исходники в `src/printbot/`, тесты в `tests/` в корне репозитория.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Инициализация проекта и структуры каталогов

- [X] T001 Создать структуру пакетов `src/printbot/{bot/routers,bot/middlewares,core/printing,core/conversion,storage,util}` и `tests/{unit,integration,contract}` с файлами `__init__.py` согласно plan.md § Project Structure
- [X] T002 Создать `pyproject.toml`: пакет `printbot`, Python >= 3.11, зависимости `aiogram~=3.25`, `aiosqlite`, `pypdf`, `pydantic-settings`, `pywin32` (маркер `sys_platform == "win32"`), extras `[dev]` — `pytest`, `pytest-asyncio`, `ruff`
- [X] T003 [P] Настроить в `pyproject.toml` секции `[tool.ruff]` и `[tool.pytest.ini_options]` (`asyncio_mode = "auto"`, `testpaths = ["tests"]`)
- [X] T004 [P] Создать `.env.example` со всеми переменными и значениями по умолчанию из `specs/001-telegram-print-bot/contracts/configuration.md`
- [X] T005 [P] Создать `printers.example.toml` с двумя блоками `[[printer]]` (Pantum 5100, GM1033ADN) по contracts/configuration.md
- [X] T006 [P] Создать `.gitignore` (`.env`, `printers.toml`, `data/`, `logs/`, `tools/SumatraPDF.exe`, `.venv/`, `__pycache__/`) и пустой каталог `tools/` с `tools/.gitkeep`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Инфраструктура, без которой не может быть реализована ни одна история

**⚠️ CRITICAL**: Ни одна пользовательская история не начинается до завершения этой фазы

- [X] T007 Реализовать загрузку и валидацию конфигурации в `src/printbot/config.py`: `.env` через pydantic-settings + разбор `printers.toml`, проверки из contracts/configuration.md (уникальность `key` и `system_name`, наличие хотя бы одного `enabled`), отказ старта с внятной ошибкой
- [X] T008 [P] Описать доменные модели и перечисления в `src/printbot/core/models.py`: `AccessStatus`, `Role`, `DocumentFormat`, `DuplexMode`, `JobStatus`, `ErrorCode`, `AuditEventType`, датаклассы `User`, `PrintJob`, `PrinterConfig` по data-model.md
- [X] T009 [P] Настроить логирование в `src/printbot/util/logging.py`: ротация в `logs/printbot.log`, уровень из `LOG_LEVEL`, фильтр-редактор, вырезающий токен бота и код доступа из сообщений
- [X] T010 [P] Реализовать работу с временными файлами в `src/printbot/util/files.py`: каталог задания `JOBS_DIR/<job_id>`, контекстный менеджер с удалением в `finally`, подметание каталогов старше часа при старте, фоновая задача очистки раз в `CLEANUP_INTERVAL_MIN` (FR-028)
- [X] T011 Реализовать подключение и миграции SQLite в `src/printbot/storage/db.py`: `aiosqlite`, `journal_mode=WAL`, `PRAGMA user_version`, создание таблиц `users`, `settings`, `print_jobs`, `audit_events` и индексов по data-model.md
- [X] T012 [P] Реализовать репозиторий пользователей в `src/printbot/storage/users.py`: получение/создание по `telegram_id`, смена `access_status`, счётчики `failed_attempts`/`locked_until`, выборка списка авторизованных
- [X] T013 [P] Реализовать репозиторий заданий и журнала в `src/printbot/storage/jobs.py`: создание задания, смена статуса с проставлением `started_at`/`finished_at`, выборки «последние N пользователя», «последние N всех», «незавершённые при старте», запись `audit_events`
- [X] T014 [P] Реализовать репозиторий настроек в `src/printbot/storage/settings.py`: чтение/запись `access_code_hash` и `schema_version` с фиксацией `updated_by`
- [X] T015 [P] Собрать все русские строки интерфейса и таблицу `ErrorCode` → текст пользователю в `src/printbot/texts.py`
- [X] T016 [P] Описать протокол печати в `src/printbot/core/printing/base.py`: `PrinterBackend`, `PrintOptions`, `PrinterInfo`, `PrinterStatus`, исключение `PrintError(code, detail)` по contracts/printer-backend.md
- [X] T017 [P] Описать протокол конвертации в `src/printbot/core/conversion/base.py`: `DocumentConverter`, исключение `ConversionError(code, detail)`
- [X] T018 [P] Реализовать `FakePrinterBackend` в `src/printbot/core/printing/fake.py`: складывает PDF в каталог, ведёт журнал вызовов, по сценарию бросает любую `PrintError`
- [X] T019 [P] Реализовать `FakeConverter` в `src/printbot/core/conversion/fake.py`: подставляет готовый PDF, по флагу бросает `ConversionError`
- [X] T020 Собрать точку входа в `src/printbot/__main__.py` и `src/printbot/bot/dispatcher.py`: чтение конфига, инициализация БД и логов, выбор бэкендов по `PRINT_BACKEND`, создание `Dispatcher`, регистрация роутеров, `start_polling`, корректное завершение по сигналу
- [X] T021 [P] Создать общие фикстуры в `tests/conftest.py`: временная БД в памяти/во временном файле с применёнными миграциями, фейковые бэкенды, тестовая конфигурация, генератор минимальных DOCX/PDF
- [X] T022 [P] Написать юнит-тесты конфигурации и миграций в `tests/unit/test_config.py` и `tests/unit/test_db.py`

**Checkpoint**: Каркас готов — можно начинать истории

---

## Phase 3: User Story 1 - Печать документа с базовыми параметрами (Priority: P1) 🎯 MVP

**Goal**: Пользователь отправляет DOCX или PDF, выбирает режим сторон и число копий, подтверждает — документ печатается, бот отвечает подтверждением.

**Independent Test**: Отправить боту корректный DOCX, пройти диалог, подтвердить — документ выходит на принтере с нужным числом копий и нужным режимом сторон, в чате есть подтверждение (spec § US1, SC-001, SC-004).

### Tests for User Story 1 ⚠️

> Тесты пишутся первыми и должны падать до реализации

- [X] T023 [P] [US1] Контрактные тесты `DocumentConverter` в `tests/contract/test_converter_contract.py`: результат существует и непуст, исходник не изменён, PDF на входе возвращается как есть, превышение таймаута даёт `TIMEOUT` без зависших процессов
- [X] T024 [P] [US1] Контрактные тесты `PrinterBackend` в `tests/contract/test_printer_backend_contract.py`: ненулевой код возврата → `PrintError`, копии и дуплекс передаются ровно один раз, `DUPLEX_LONG` на принтер без дуплекса → `INTERNAL`, «сырые» исключения наружу не выходят
- [X] T025 [P] [US1] Юнит-тесты валидации документов в `tests/unit/test_documents.py`: определение DOCX/PDF по сигнатуре, отказ по расширению-обманке, превышение размера, зашифрованный PDF, OLE-файл, подсчёт страниц
- [X] T026 [P] [US1] Интеграционный тест счастливого пути в `tests/integration/test_print_flow.py`: документ → дуплекс → копии → подтверждение → задание `DONE`, фейковый принтер получил ровно один вызов с верными `PrintOptions`
- [X] T027 [P] [US1] Юнит-тесты переходов статусов задания в `tests/unit/test_jobs.py`: допустимые переходы по data-model.md, недопустимые отвергаются, финальные статусы неизменяемы

### Implementation for User Story 1

- [X] T028 [P] [US1] Реализовать `src/printbot/core/documents.py`: определение формата по сигнатуре (`%PDF-`, `PK\x03\x04` + `word/document.xml`, OLE `D0CF11E0`), проверка размера и целостности, `is_encrypted` через `pypdf`, подсчёт страниц готового PDF (FR-001…FR-005)
- [X] T029 [US1] Реализовать `LibreOfficeConverter` в `src/printbot/core/conversion/libreoffice.py`: вызов `soffice.exe --headless --norestore -env:UserInstallation=file:///<профиль задания> --convert-to pdf --outdir` через `asyncio.create_subprocess_exec`, таймаут `CONVERT_TIMEOUT_S` с принудительным завершением, отображение сбоев в `ErrorCode` (research.md R2)
- [X] T030 [US1] Реализовать `WindowsPrinterBackend` в `src/printbot/core/printing/windows.py`: печать через `SumatraPDF.exe -print-to ... -print-settings "<duplexlong|simplex>,<N>x,paper=A4,monochrome" -silent -exit-when-done`, разбор кода возврата, таймаут `PRINT_TIMEOUT_S` (research.md R3)
- [X] T031 [US1] Реализовать базовый `PrinterRegistry` в `src/printbot/core/printers.py`: список принтеров из конфига, сопоставление с системными именами, определение принтера по умолчанию для одного включённого принтера
- [X] T032 [US1] Реализовать `JobService` в `src/printbot/core/jobs.py`: `asyncio.Queue` и воркер на каждый принтер, конвейер `QUEUED → CONVERTING → PRINTING → DONE/FAILED`, запись статусов через репозиторий, гарантированная очистка каталога задания (FR-016, FR-028)
- [X] T033 [P] [US1] Описать состояния диалога в `src/printbot/bot/states.py`: `PrintFlow.choosing_printer/choosing_duplex/entering_copies/confirming`, `AuthFlow.waiting_code`
- [X] T034 [P] [US1] Реализовать клавиатуры и схему `callback_data` в `src/printbot/bot/keyboards.py`: префиксы `dx`, `cp`, `ok`, `big` (и `pr` — задел для US2), длина значения ≤ 64 байт (contracts/bot-interaction.md)
- [X] T035 [US1] Реализовать роутер печати в `src/printbot/bot/routers/printing.py`: приём документа, отказы по формату/размеру/повреждению, шаги дуплекса и копий (текстом и кнопками, диапазон 1…50), сводка и подтверждение, отмена, обработка нового файла посреди диалога (FR-006…FR-010)
- [X] T036 [US1] Реализовать общий роутер в `src/printbot/bot/routers/common.py`: `/start`, `/help`, `/cancel`, истечение незавершённого диалога по `DIALOG_TIMEOUT_MIN` с удалением файла (FR-011)
- [X] T037 [US1] Подключить роутеры печати и общий, `JobService` и бэкенды в `src/printbot/bot/dispatcher.py` и `src/printbot/__main__.py`; запустить воркеры печати вместе с polling

**Checkpoint**: US1 работает целиком — это MVP, его можно ставить на офисный компьютер

---

## Phase 4: User Story 2 - Выбор принтера из подключённых (Priority: P2)

**Goal**: Пользователь выбирает принтер из списка; недоступные помечены, дуплекс предлагается только там, где поддерживается.

**Independent Test**: С двумя настроенными принтерами отправить файл — бот показывает оба с признаком доступности, документ выходит на выбранном; с одним принтером шаг выбора пропускается (spec § US2, SC-008).

### Tests for User Story 2 ⚠️

- [X] T038 [P] [US2] Интеграционный тест выбора принтера в `tests/integration/test_printer_selection.py`: два принтера → шаг выбора и печать на выбранном; один принтер → шаг пропущен; выключенный принтер не выбирается
- [X] T039 [P] [US2] Юнит-тесты реестра принтеров в `tests/unit/test_printers.py`: сопоставление флагов `win32print` с `ErrorCode`, приоритет `supports_duplex` из конфига над автоопределением, принтер из конфига отсутствует в системе → недоступен, старт не падает

### Implementation for User Story 2

- [X] T040 [US2] Расширить `src/printbot/core/printing/windows.py`: `list_printers` через `EnumPrinters`, `get_status` через `GetPrinter(handle, 2)` с разбором `Status`/`Attributes`/`cJobs`, определение дуплекса через `DeviceCapabilities(..., DC_DUPLEX)` (contracts/printer-backend.md)
- [X] T041 [US2] Расширить `src/printbot/core/printers.py`: опрос доступности перед показом списка, кеш статуса на несколько секунд, `status_reason` для сообщения пользователю, учёт флага `enabled` (FR-013, FR-015)
- [X] T042 [US2] Добавить шаг выбора принтера в `src/printbot/bot/routers/printing.py` и клавиатуру `pr:<key>` в `src/printbot/bot/keyboards.py`; пропускать шаг при единственном доступном принтере (FR-014)
- [X] T043 [US2] Скрывать вариант «двусторонняя» для принтеров без дуплекса и пояснять причину в `src/printbot/bot/routers/printing.py` (FR-008)
- [X] T044 [US2] Реализовать команду `/printers` в `src/printbot/bot/routers/common.py` — список принтеров с признаком доступности

**Checkpoint**: US1 и US2 работают независимо

---

## Phase 5: User Story 3 - Доступ к боту по общему коду (Priority: P2)

**Goal**: Печатать может только тот, кто ввёл действующий код доступа; перебор кода блокируется.

**Independent Test**: С неавторизованного аккаунта отправить файл — печати нет, запрошен код; ввести верный код — печать проходит и код больше не спрашивается (spec § US3, SC-006).

### Tests for User Story 3 ⚠️

- [X] T045 [P] [US3] Юнит-тесты кода доступа в `tests/unit/test_access.py`: формат хеша `scrypt$...`, сверка через `compare_digest`, 5 неверных попыток → блокировка на 15 минут, блокировка переживает перезапуск, успешный ввод сбрасывает счётчики
- [X] T046 [P] [US3] Интеграционный тест авторизации в `tests/integration/test_access_flow.py`: файл от неавторизованного не скачивается и не печатается; после верного кода печать работает; после `/revoke` снова требуется код

### Implementation for User Story 3

- [X] T047 [US3] Реализовать `AccessService` в `src/printbot/core/access.py`: генерация случайного кода при первом старте с однократным выводом в консоль, `scrypt`-хеш с солью, проверка, счётчики попыток и блокировка по `LOCKOUT_ATTEMPTS`/`LOCKOUT_MINUTES` (FR-021, FR-022)
- [X] T048 [US3] Реализовать middleware авторизации в `src/printbot/bot/middlewares/auth.py`: пропускать дальше только `ALLOWED`, остальных уводить в `AuthFlow.waiting_code` до скачивания файла (FR-020)
- [X] T049 [US3] Реализовать роутер авторизации в `src/printbot/bot/routers/auth.py`: приём кода, удаление сообщения с кодом из чата, сообщение об оставшемся времени блокировки, назначение роли `ADMIN` по `ADMIN_IDS` при первом обращении
- [X] T050 [US3] Записывать события `ACCESS_GRANTED`, `ACCESS_DENIED`, `LOCKOUT_STARTED` в `audit_events` из `src/printbot/core/access.py` (FR-022, FR-026)

**Checkpoint**: US1–US3 работают независимо; бот безопасен для размещения в офисе

---

## Phase 6: User Story 4 - Понятная обратная связь по статусу задания (Priority: P3)

**Goal**: Автор задания видит его судьбу: принято, отправлено на принтер, ошибка с понятной причиной, прерывание при перезапуске.

**Independent Test**: Отправить задание на выключенный принтер — бот сообщает о недоступности с понятной причиной, задание получает финальный статус, а не «зависает» (spec § US4, SC-005).

### Tests for User Story 4 ⚠️

- [X] T051 [P] [US4] Интеграционный тест статусов и ошибок в `tests/integration/test_job_statuses.py`: фейковый принтер возвращает `PRINTER_OFFLINE`, `PAPER_OUT`, `TIMEOUT` — автор получает разные понятные сообщения, задание завершается `FAILED` с верным `error_code`
- [X] T052 [P] [US4] Интеграционный тест восстановления после перезапуска в `tests/integration/test_restart_recovery.py`: задания в `QUEUED`/`PRINTING` после старта переходят в `FAILED` с `INTERRUPTED`, авторам уходит уведомление

### Implementation for User Story 4

- [X] T053 [US4] Отправлять уведомления при смене статуса из `src/printbot/core/jobs.py`: принято (с номером задания и позицией в очереди) и финальный результат — только автору задания (FR-017, US4 сценарий 4)
- [X] T054 [US4] Реализовать единый обработчик ошибок в `src/printbot/bot/middlewares/errors.py`: любое необработанное исключение → понятное сообщение из `texts.py`, техническая деталь только в лог и `print_jobs.error_detail`
- [X] T055 [US4] Реализовать восстановление при старте в `src/printbot/core/jobs.py`: незавершённые задания → `FAILED(INTERRUPTED)` с уведомлением и предложением повторить, без автоматической перепечатки (research.md R8, FR-019)
- [X] T056 [US4] Реализовать команду `/status` в `src/printbot/bot/routers/common.py` — последние 5 заданий пользователя с их статусами
- [X] T057 [US4] Добавить дополнительное подтверждение объёмного документа (`big:go`) при `page_count > LARGE_DOC_PAGES` в `src/printbot/bot/routers/printing.py`

**Checkpoint**: Ни одно задание не остаётся без внятного финального статуса

---

## Phase 7: User Story 5 - Обзор заданий и управление доступом для администратора (Priority: P3)

**Goal**: Администратор видит журнал заданий, меняет код доступа, отзывает доступ, видит список пользователей.

**Independent Test**: От аккаунта администратора запросить `/journal` — в списке ранее выполненные задания с параметрами; та же команда от обычного пользователя отклоняется (spec § US5, SC-011).

### Tests for User Story 5 ⚠️

- [X] T058 [P] [US5] Интеграционный тест админ-команд в `tests/integration/test_admin.py`: `/journal`, `/setcode`, `/revoke`, `/users` доступны только `ADMIN`; обычный пользователь получает отказ и не видит их в `/help`
- [X] T059 [P] [US5] Юнит-тест выборки журнала в `tests/unit/test_journal_query.py`: сортировка по убыванию времени, ограничение N, наличие всех полей отчёта

### Implementation for User Story 5

- [X] T060 [US5] Реализовать роутер администратора в `src/printbot/bot/routers/admin.py` с проверкой роли и командой `/journal [N]` — автор, файл, параметры, принтер, время, результат (FR-025, FR-026)
- [X] T061 [US5] Реализовать `/setcode` в `src/printbot/bot/routers/admin.py`: диалог смены кода, удаление сообщения с новым кодом, немедленное вступление в силу, событие `CODE_CHANGED` (FR-023)
- [X] T062 [US5] Реализовать `/revoke <telegram_id>` и `/users` в `src/printbot/bot/routers/admin.py` с записью события `ACCESS_REVOKED` (FR-024)
- [X] T063 [US5] Реализовать явное удаление записей журнала администратором с событием `JOURNAL_PURGED` в `src/printbot/storage/jobs.py` и `src/printbot/bot/routers/admin.py` (FR-027)

**Checkpoint**: Все пять историй работают независимо

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Эксплуатация, приёмка и сквозные проверки

- [X] T064 [P] Написать `tools/list_printers.py` — вывод системных имён принтеров и поддержки дуплекса для заполнения `printers.toml`
- [X] T065 [P] Написать `README.md`: установка, `.env`, `printers.toml`, автозапуск через Планировщик заданий, ссылки на `specs/001-telegram-print-bot/quickstart.md`
- [X] T066 Интеграционный тест конкурентности в `tests/integration/test_concurrency.py`: 5 одновременных заданий от разных пользователей на один принтер — все выполнены, порядок вызовов принтера строго последовательный (SC-010)
- [X] T067 Проверить отсутствие секретов в логах: тест в `tests/unit/test_logging.py` на то, что токен и код доступа вырезаются фильтром `src/printbot/util/logging.py`
- [X] T068 Прогнать весь набор тестов и устранить замечания `ruff` по всему `src/printbot/`
- [ ] T069 Выполнить приёмочные сценарии 6.1–6.10 из `specs/001-telegram-print-bot/quickstart.md` на реальном хосте Windows
- [ ] T070 Проверить маппинг `duplexlong`/`duplexshort` отдельно на Pantum 5100 и GM1033ADN и зафиксировать результат в `printers.toml` и `README.md` (research.md R3)
- [ ] T071 Замерить время «подтверждение → начало печати» на документе в 10 страниц и подтвердить SC-002, зафиксировав результат в `specs/001-telegram-print-bot/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: без зависимостей, стартует сразу
- **Foundational (Phase 2)**: после Setup — блокирует все истории
- **User Stories (Phase 3–7)**: после Foundational; далее либо параллельно, либо по приоритету P1 → P2 → P3
- **Polish (Phase 8)**: после нужных историй

### User Story Dependencies

- **US1 (P1)**: только Foundational. Работает с одним принтером из конфига, без авторизации — это осознанный MVP-срез
- **US2 (P2)**: только Foundational. Технически расширяет диалог US1, но проверяется отдельным сценарием
- **US3 (P2)**: только Foundational. Не зависит от US1/US2 — middleware перехватывает любые сообщения
- **US4 (P3)**: только Foundational; полностью осмыслен поверх US1, поэтому в одиночку выпускать не следует
- **US5 (P3)**: Foundational + записи в журнале (появляются после US1) или подготовленные тестовые данные

### Within Each User Story

- Тесты пишутся первыми и должны падать до реализации
- Модели → сервисы → роутеры бота → подключение в диспетчер
- Задача считается завершённой, когда её тесты зелёные

### Parallel Opportunities

- Phase 1: T003–T006 параллельно
- Phase 2: T008, T009, T010 параллельно; после T011 — T012, T013, T014 параллельно; T015–T019 параллельно
- Phase 3: T023–T027 (тесты) параллельно; T028, T033, T034 параллельно
- Phase 4–7: тесты каждой истории параллельны между собой
- При наличии нескольких исполнителей US1, US2 и US3 ведутся параллельно после Foundational

---

## Parallel Example: User Story 1

```bash
# Сначала все тесты истории — параллельно:
Task: "Контрактные тесты DocumentConverter в tests/contract/test_converter_contract.py"
Task: "Контрактные тесты PrinterBackend в tests/contract/test_printer_backend_contract.py"
Task: "Юнит-тесты валидации документов в tests/unit/test_documents.py"
Task: "Интеграционный тест счастливого пути в tests/integration/test_print_flow.py"
Task: "Юнит-тесты переходов статусов в tests/unit/test_jobs.py"

# Затем независимые модули — параллельно:
Task: "Реализовать core/documents.py"
Task: "Реализовать bot/states.py"
Task: "Реализовать bot/keyboards.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1: Setup (T001–T006)
2. Phase 2: Foundational (T007–T022) — блокирует всё остальное
3. Phase 3: User Story 1 (T023–T037)
4. **STOP и ПРОВЕРИТЬ**: сценарии 6.1–6.3 из quickstart.md на реальном принтере
5. MVP можно ставить на офисный компьютер: печать DOCX и PDF с выбором сторон и копий на одном принтере

### Incremental Delivery

1. Setup + Foundational → каркас готов
2. + US1 → печать работает (MVP)
3. + US3 → бот безопасно открывать сотрудникам (до этого момента доступ к боту не ограничивать!)
4. + US2 → выбор из двух принтеров
5. + US4 → внятные статусы и восстановление после перезапуска
6. + US5 → журнал и администрирование
7. Phase 8 → приёмка на хосте

> **Порядок выпуска отличается от порядка приоритетов**: US1 без US3 не следует давать сотрудникам «в открытую» — до появления кода доступа бот должен быть известен только тестировщику.

### Parallel Team Strategy

1. Команда вместе делает Setup + Foundational
2. Затем: разработчик A — US1, разработчик B — US3 (независимая ветка middleware + auth), разработчик C — US2 после T031
3. US4 и US5 подключаются, когда US1 закрыт

---

## Notes

- `[P]` = разные файлы, нет зависимостей
- Метка `[Story]` даёт прослеживаемость до истории спеки
- Проверять падение теста до реализации
- Коммит после каждой задачи или логической группы
- На каждом Checkpoint можно остановиться и проверить историю изолированно
- `core/printing/windows.py` и `core/conversion/libreoffice.py` — единственные модули, требующие реального хоста Windows; всё остальное проверяется на фейках на любой машине
