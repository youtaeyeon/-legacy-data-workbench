# 병원 계약정보·마케팅 위키 MVP 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 목업 Excel을 읽어 병원 정보를 지속 저장하고, 변경분을 반영해 병원별 Markdown·필터 HTML·마케팅 Excel을 생성하는 Windows 데스크톱 MVP를 만든다.

**Architecture:** PySide6 앱은 경로·설정 UI와 작업 흐름을 담당한다. Excel importer는 병원 ID 기준으로 SQLite를 갱신하고, 출력 생성기는 DB에서 Markdown·정적 HTML·Excel을 만든다. AI는 공통 provider 인터페이스와 기본 mock provider로 분리하며, 설정 비밀값은 OS credential store에 둔다.

**Tech Stack:** Python 3.12+, PySide6, pytest, openpyxl, sqlite3, keyring, PyInstaller.

**Spec:** `docs/superpowers/specs/2026-11-05-hospital-marketing-mvp-design.md`

## Global Constraints

- Windows 데스크톱 EXE를 목표로 하고, source/target 경로는 실행 중 설정할 수 있어야 한다.
- 과제 테스트는 목업 데이터만 사용하며 기본 mock mode는 네트워크와 API 키 없이 동작한다.
- Source directory import options are user-selectable from `.xlsx`, `.csv`, `.docx`, `.pptx`, `.pdf`, `.txt`, `.md`, `.html`; `.doc`/`.ppt` legacy binaries and image-only PDF OCR are out of scope.
- Every enabled source file is converted to a Markdown wiki document; XLSX/CSV structured tables also update SQLite when recognized.
- Mock mode must convert documents deterministically without network or API keys.
- The source folder remains read-only; selected extension settings persist with other app preferences.
- The folder/Source/Target/processing section labels requested by the user render black (`#000000`).
- `hospital_id` is the merge key. 병원명을 기준으로 추정 매칭하지 않는다.
- SQLite가 기준 데이터이고 Markdown/HTML/Excel은 생성 결과다.
- 원본 Excel은 수정하지 않는다. 병원 삭제는 자동 반영하지 않는다.
- 제품 콘텐츠 판별 기준은 `울트라클리어`, `리뉴비온`, `피아모`다.
- API 키는 설정 파일·로그·생성 결과에 평문으로 저장하지 않는다.
- 변경이 생기는 Git 명령은 `main`이 아닌 기능 브랜치에서만 실행하고, 커밋·푸시는 사용자 확인 전 하지 않는다.

## Review Focus

- 병원 ID 누락·중복·잘못된 값: 잘못된 행을 임의 연결하지 않고 행 번호를 보고한다. — Task 3의 importer 오류 테스트.
- 동일 ID의 변경 없는 재수입 및 일부 필드 누락: 중복 추가나 기존 정보의 임의 삭제가 없어야 한다. — Task 3의 idempotent/partial-field 테스트.
- DB transaction 중간 실패: 부분 데이터만 저장된 것처럼 보이면 안 된다. — Task 2/3의 rollback 테스트.
- 오프라인 mock mode: 네트워크·API 키가 없어도 import 및 콘텐츠 분류가 재현 가능해야 한다. — Task 6의 no-network 테스트.
- 생성된 HTML과 API 키 안전: HTML은 로컬에서 필터되어야 하고 키는 어떤 산출물에도 없어야 한다. — Task 5/6의 산출물·비밀값 검사.

---

### Task 1: 프로젝트 골격과 목업 입력 데이터

**Files:**
- Create: `pyproject.toml`
- Create: `src/hospital_marketing/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_mock_fixtures.py`
- Create: `scripts/create_mock_workbooks.py`
- Create: `fixtures/source/initial/initial_hospitals.xlsx`
- Create: `fixtures/source/initial/marketing_details.xlsx`
- Create: `fixtures/source/weekly/weekly_update.xlsx`
- Create: `fixtures/source/weekly/marketing_details.xlsx`

**Interfaces:**
- `scripts.create_mock_workbooks.build_fixtures(output_dir: Path) -> None`
- Initial workbook contains stable `hospital_id` rows; weekly workbook contains one new, one changed, one unchanged hospital; details workbook contains products, materials, channels, and relevant/irrelevant content candidates.

- [ ] **Step 1: Write failing fixture contract tests** — assert workbook names/sheets, required headers, stable IDs across initial and update files, and expected new/changed/unchanged rows.
- [ ] **Step 2: Run `pytest tests/test_mock_fixtures.py -q` and confirm failure** because fixture builder and package are absent.
- [ ] **Step 3: Add package metadata and deterministic fixture builder** — all hospital and channel names are explicitly fictional; products use the three approved names.
- [ ] **Step 4: Re-run the fixture tests** — confirm the contract and reproducibility.

### Task 2: Domain models, SQLite schema, and repository

**Files:**
- Create: `src/hospital_marketing/domain.py`
- Create: `src/hospital_marketing/repository.py`
- Create: `tests/test_repository.py`

**Interfaces:**
- `Hospital`, `EquipmentDelivery`, `MarketingMaterial`, `Channel`, `ContentItem` dataclasses.
- `Repository(db_path: Path)` with `initialize()`, `get_hospital(hospital_id)`, `upsert_hospital(hospital)`, and transaction context.

- [ ] **Step 1: Write failing repository tests** — schema initialization, upsert by ID, related records, transaction rollback, and safe reopen persistence.
- [ ] **Step 2: Run `pytest tests/test_repository.py -q` and confirm expected missing-module/API failures.**
- [ ] **Step 3: Implement typed domain records and SQLite tables/constraints** — use foreign keys, unique `hospital_id`, and explicit transaction boundaries.
- [ ] **Step 4: Re-run repository tests** — confirm persistence and rollback behavior.

### Task 3: Excel ingestion, validation, and change detection

**Files:**
- Create: `src/hospital_marketing/importer.py`
- Create: `src/hospital_marketing/diff.py`
- Create: `src/hospital_marketing/report.py`
- Create: `tests/test_importer.py`
- Modify: `src/hospital_marketing/repository.py`

**Interfaces:**
- `ImportService(repository: Repository)` with `import_folder(source_dir: Path) -> ImportReport`.
- `ImportReport` includes per-file status, inserted/updated/unchanged counts, missing/deleted candidates, and row-level errors.
- `compare_hospital(incoming: Hospital, stored: Hospital) -> list[FieldChange]`.

- [ ] **Step 1: Write failing importer tests** — initial import; second import with one added/one changed/one unchanged ID; duplicate/missing ID; missing optional fields; malformed date; deleted source row does not delete; bad-file transaction rollback.
- [ ] **Step 2: Run `pytest tests/test_importer.py -q` and confirm expected failures.**
- [ ] **Step 3: Implement Excel readers and ID-based diff** — use openpyxl read-only mode; validate required headers; produce row/sheet-specific errors; persist successful valid files atomically and never modify source workbooks.
- [ ] **Step 4: Re-run importer tests** — assert exact counts, DB values, and report errors.

### Task 4: Mock AI provider and product relevance classification

**Files:**
- Create: `src/hospital_marketing/ai/base.py`
- Create: `src/hospital_marketing/ai/mock.py`
- Create: `src/hospital_marketing/ai/registry.py`
- Create: `tests/test_ai_mock.py`

**Interfaces:**
- `AIProvider` protocol: `classify_content(item: ContentItem, products: Sequence[str]) -> RelevanceResult` and `summarize_hospital(hospital: Hospital) -> str`.
- `MockProvider` produces deterministic outputs from fixture records without network calls.
- `ProviderRegistry.available() -> Sequence[str]` and `create(provider_id: str) -> AIProvider`.

- [ ] **Step 1: Write failing mock provider tests** — exact product-related vs unrelated classifications, stable evidence text, unknown content handling, and no HTTP/network invocation.
- [ ] **Step 2: Run `pytest tests/test_ai_mock.py -q` and confirm failure.**
- [ ] **Step 3: Implement the protocol, registry, and deterministic mock rules** — include only related items in generated results; keep irrelevant status in import report.
- [ ] **Step 4: Re-run AI mock tests** — verify deterministic output with no credentials or network.

### Task 5: Markdown, static HTML dashboard, and Excel export

**Files:**
- Create: `src/hospital_marketing/outputs/markdown.py`
- Create: `src/hospital_marketing/outputs/dashboard.py`
- Create: `src/hospital_marketing/outputs/excel.py`
- Create: `src/hospital_marketing/outputs/generate.py`
- Create: `tests/test_outputs.py`
- Create: `src/hospital_marketing/templates/dashboard.html`

**Interfaces:**
- `generate_outputs(repository: Repository, target_dir: Path, provider: AIProvider | None = None) -> OutputManifest`.
- Markdown path: `target/wiki/<hospital_id>.md`.
- Dashboard path: `target/dashboard/index.html`; data and client-side filters embedded in the HTML.
- Excel path: `target/exports/marketing.xlsx` with separate hospitals, deliveries, materials, channels, and relevant content sheets.

- [ ] **Step 1: Write failing output tests** — per-hospital Markdown fields, no irrelevant content, standalone HTML with hospital/product/platform filtering, Excel sheet names/values, no local resource dependencies, and safe handling of special characters.
- [ ] **Step 2: Run `pytest tests/test_outputs.py -q` and confirm expected failures.**
- [ ] **Step 3: Implement renderers from SQLite records** — escape HTML/Markdown values appropriately; embed dashboard data and filter logic; create target directories.
- [ ] **Step 4: Re-run output tests** — verify exact files, fields, and filter contracts.

### Task 6: Settings and secure provider credentials

**Files:**
- Create: `src/hospital_marketing/settings.py`
- Create: `src/hospital_marketing/credentials.py`
- Create: `src/hospital_marketing/ai/openai_provider.py`
- Create: `src/hospital_marketing/ai/anthropic_provider.py`
- Create: `src/hospital_marketing/ai/gemini_provider.py`
- Create: `tests/test_settings.py`
- Create: `tests/test_credentials.py`
- Create: `tests/test_ai_adapters.py`

**Interfaces:**
- `AppSettings(source_dir: Path | None, target_dir: Path | None, provider_id: str, model_id: str, mock_mode: bool)`.
- `SettingsStore.load() -> AppSettings`, `save(settings: AppSettings) -> None` stores non-secret preferences under the OS application config directory.
- `CredentialStore.set(provider_id: str, api_key: str)`, `get(provider_id: str) -> str | None`, `delete(provider_id: str) -> None` delegates to keyring.
- Provider adapters implement `AIProvider` and accept injected HTTP clients for deterministic tests.

- [ ] **Step 1: Write failing settings/credentials/adapter tests** — persisted paths/provider choice; key is not present in serialized settings or logs; keyring get/set/delete; request serialization for each supported adapter; missing key surfaces a safe user-facing error.
- [ ] **Step 2: Run targeted tests and confirm expected failures.**
- [ ] **Step 3: Implement settings persistence, keyring wrapper, and provider adapters** — no key goes into SQLite or generated files; mock mode remains default.
- [ ] **Step 4: Re-run all Task 6 tests** — inspect test logs and temporary outputs to assert secrets are absent.

### Task 7: PySide6 desktop workflow

**Files:**
- Create: `src/hospital_marketing/app.py`
- Create: `src/hospital_marketing/ui/main_window.py`
- Create: `src/hospital_marketing/ui/settings_dialog.py`
- Create: `src/hospital_marketing/ui/workflow.py`
- Create: `tests/test_workflow.py`
- Create: `tests/test_ui_smoke.py`

**Interfaces:**
- `MainWindow(settings_store: SettingsStore, workflow: ImportWorkflow)`.
- `ImportWorkflow.run(source_dir: Path, target_dir: Path) -> ImportReport` calls import, repository, AI, and output generation in that order.
- UI exposes source/target directory selection, provider/model/mock settings, import action, progress/result summary, and open-dashboard action.

- [ ] **Step 1: Write failing workflow/UI tests** — first-run missing paths prompt; selecting paths persists settings; run displays import counts/errors; dashboard open uses target output path; mock mode does not require a key.
- [ ] **Step 2: Run targeted tests offscreen with `QT_QPA_PLATFORM=offscreen pytest tests/test_workflow.py tests/test_ui_smoke.py -q` and confirm failure.**
- [ ] **Step 3: Implement a minimal functional PySide6 UI** — keep UI handlers thin and delegate processing to `ImportWorkflow`.
- [ ] **Step 4: Re-run UI tests and full `pytest -q`** — confirm all modules work together.

### Task 8: End-to-end scenario and Windows packaging

**Files:**
- Create: `tests/test_end_to_end.py`
- Create: `scripts/package_windows.ps1`
- Create: `README.md`
- Create: `hospital-marketing.spec`

**Interfaces:**
- End-to-end scenario imports the initial workbook, generates outputs, imports weekly update, then checks final DB/output contents.
- Packaging script builds a single-folder or one-file Windows executable from the tested entry point; final selection favors reliable Qt plugin collection.

- [ ] **Step 1: Write failing end-to-end test** — assert initial and update counts, persistent hospital records, Markdown count, dashboard filter data, workbook export rows, and no irrelevant content.
- [ ] **Step 2: Run `pytest tests/test_end_to_end.py -q` and confirm failure.**
- [ ] **Step 3: Integrate app startup and packaging configuration** — document Windows-native build prerequisites and source/target folder setup; do not claim Windows EXE verified until it is built and launched on Windows.
- [ ] **Step 4: Run full `pytest -q` in WSL/Linux, then build and smoke-test the Windows EXE on Windows.**
- [ ] **Step 5: Report any Windows-only verification limitation explicitly.**

### Task 9: Selectable multi-format Markdown ingestion

**Files:**
- Create: `src/hospital_marketing/documents/__init__.py`
- Create: `src/hospital_marketing/documents/readers.py`
- Create: `src/hospital_marketing/documents/conversion.py`
- Create: `src/hospital_marketing_launcher.py`
- Create: `tests/test_documents.py`
- Create: `tests/test_launcher.py` (already present; preserve and extend only if required)
- Modify: `src/hospital_marketing/ai/base.py`
- Modify: `src/hospital_marketing/ai/mock.py`
- Modify: `src/hospital_marketing/ai/adapters/base.py`
- Modify: `src/hospital_marketing/ai/registry.py`
- Modify: `src/hospital_marketing/settings.py`
- Modify: `src/hospital_marketing/importer.py`
- Modify: `src/hospital_marketing/workflow.py`
- Modify: `src/hospital_marketing/ui/main_window.py`
- Modify: `pyproject.toml`, `README.md`, `hospital-marketing.spec`
- Modify: `tests/test_settings.py`, `tests/test_importer.py`, `tests/test_workflow.py`, `tests/test_ui_smoke.py`, `tests/test_ai_adapters.py`

**Interfaces:**
- `SUPPORTED_EXTENSIONS = (".xlsx", ".csv", ".docx", ".pptx", ".pdf", ".txt", ".md", ".html")`.
- `extract_document_text(path: Path) -> ExtractedDocument` returns plain text plus `source_relative_path` and `extension` metadata.
- `AIProvider.convert_document_to_markdown(source_name: str, extracted_text: str) -> str` produces Markdown without inventing facts.
- `AppSettings.enabled_extensions: tuple[str, ...]` persists selected extensions; default is all supported extensions.
- `ImportWorkflow.run(..., enabled_extensions: Sequence[str] | None = None) -> WorkflowResult` applies the user's enabled extension selection.
- Markdown source output is stable at `target/wiki/source-documents/<relative-name>_<extension>.md` to avoid collisions.

- [ ] **Step 1: Write failing tests** — create representative mock XLSX/CSV/DOCX/PPTX/PDF/TXT/MD/HTML; assert text/table extraction, relative-path metadata, collision-safe Markdown paths, and empty/scanned PDF reporting; assert XLSX/CSV with hospital headers still update structured DB; assert other formats create Markdown docs; assert disabled types are skipped; assert extension settings round-trip and UI labels are black; assert MockProvider conversion makes no network request.
- [ ] **Step 2: Run targeted document/settings/importer/workflow/UI tests and confirm failure** because document readers, AI conversion, and selection controls are absent.
- [ ] **Step 3: Add runtime readers** — stdlib `csv`/`html.parser`, `python-docx`, `python-pptx`, `pypdf`; add `reportlab` as a test-only PDF fixture dependency. Preserve page/slide/table order; PDF text-layer only, no OCR.
- [ ] **Step 4: Implement source Markdown conversion** — pass extracted text to the selected AI provider, use a deterministic offline MockProvider conversion, write one stable Markdown document per enabled source file, and report extraction/conversion failures without modifying source files.
- [ ] **Step 5: Implement extension selection and CSV structured import** — persist checkbox selections in app settings; route selected XLSX/CSV to ID-based importer and all selected formats to Markdown conversion.
- [ ] **Step 6: Run targeted tests, then full `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q`** — verify all formats, selection persistence, mock no-network behavior, Markdown output, and unchanged prior importer/dashboard functionality.

### Task 10: Rebuild and inspect the updated Windows app

**Files:**
- Modify: `scripts/package_windows.ps1`, `hospital-marketing.spec`, `README.md` as needed.

**Interfaces:**
- Windows build output remains isolated under `dist-win/` and `build-win/`.
- Launch the rebuilt EXE from Windows Python 3.12+ and verify the updated extension controls and black section labels.

- [ ] **Step 1: Run the full Windows test suite** through `scripts/package_windows.ps1` with the already-installed Windows venv.
- [ ] **Step 2: Build the Windows onedir EXE** and verify its expected path exists.
- [ ] **Step 3: Launch the EXE and inspect the actual UI** — confirm extension checkboxes, file paths, AI settings, and non-secret-safe status text.
- [ ] **Step 4: Run a mock folder import from the UI** and verify Markdown documents and existing dashboard/Excel outputs are created.

## Self-review

- **Spec coverage:** source/target settings, first full import, incremental diff, SQLite, hospital and source-document Markdown, selectable multi-format extraction, AI conversion/providers, standalone filter HTML, Excel export, error reports, offline mock mode, secret storage, and Windows packaging are mapped to Tasks 1–10.
- **Step scan:** each new task starts with failing tests, verifies the failure, implements the required behavior, and runs targeted plus full tests.
- **Type consistency:** repository, AI provider, document reader, import, settings, workflow, and output interfaces are specified at their consumer boundaries.
- **Review Focus:** data safety, file format selection, AI no-network mock mode, HTML and secret safety have named tests.
- **Proportion:** implementation details are limited to interfaces, files, and observable behaviors needed to split work.

## Execution Handoff

The plan intentionally contains no commit/push steps because those require explicit user approval. Keep implementation on a feature branch, never `main`; ask before creating commits. The plan is saved at `docs/superpowers/plans/2026-11-05-hospital-marketing-mvp.md`.
