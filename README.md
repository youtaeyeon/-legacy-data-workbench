# 병원 마케팅 위키 MVP

영업부 Excel·CSV와 Word·PowerPoint·PDF 등 여러 원본 파일을 읽어 마케팅팀 병원 위키와 대시보드를 만드는 과제용 Windows 앱입니다. 실제 회사 자료 대신 가상 목업 데이터만 사용합니다.

## 기능

- 앱에서 읽을 확장자를 선택할 수 있고, 설정을 다음 실행에도 유지
- XLSX·CSV의 병원 필드는 병원 ID 기준으로 신규·변경·변경 없음 판별 및 이력 저장
- XLSX/CSV/DOCX/PPTX/PDF/TXT/MD/HTML 원본의 본문·표를 추출해 AI Markdown 위키로 저장
- DOCX 문단·표, PPTX 슬라이드·표, PDF 텍스트 레이어를 읽음 (스캔 PDF OCR은 미지원)
- 납품 장비, 마케팅 물품, SNS 채널과 콘텐츠 후보 연결
- 목업 AI 기본 모드에서 울트라클리어·리뉴비온·피아모 관련 콘텐츠만 분류
- 병원별 Markdown, 원본별 Markdown, 필터 가능한 단일 HTML, 마케팅 Excel 생성
- OpenAI, Anthropic, Gemini 선택형 adapter 구조
- source/target 폴더와 AI 설정 저장, API 키는 OS 자격 증명 저장소에 보관

지원 확장자는 `.xlsx`, `.csv`, `.docx`, `.pptx`, `.pdf`, `.txt`, `.md`, `.html`입니다. CSV/XLSX는 병원 필드 헤더가 식별될 때 정형 데이터에도 반영하고, 모든 선택 파일은 `target/wiki/source-documents/` 아래 Markdown으로 저장합니다. 구형 `.doc`/`.ppt`와 이미지 PDF OCR은 지원하지 않습니다.

실제 웹 검색·SNS 수집과 실제 회사 파일 사용은 과제 MVP 범위에 포함하지 않습니다. 기본 목업 모드는 네트워크나 API 키가 필요 없습니다. 실제 AI 제공자를 선택하면 선택한 파일에서 추출한 내용이 해당 외부 AI 제공자에 전송됩니다.

## AI 설정 가이드

- 기본 연결은 PC에 설치·로그인한 Claude CLI를 이용하는 개인 구독 계정입니다. 앱의 AI 설정 창에서 `구독 계정 연결 (권장)` 아래 CLI를 선택하고 설치 상태를 확인하세요. 서비스 약관과 사용량 한도가 적용됩니다.
- API 키 연결은 선택 사항이며, 설정 창의 `API 키 사용 (선택)` 영역을 펼쳐 제공자와 키를 지정합니다.
- OpenAI API 키: [API keys](https://platform.openai.com/api-keys) · 모델 예시: `gpt-6-luna`, `gpt-6.1-sol`, `gpt-6-astra`
- Anthropic API 키: [Console](https://console.anthropic.com/settings/keys) · 모델 예시: `claude-haiku-5-5`, `claude-sonnet-5-5`, `claude-opus-5-5`
- Gemini API 키: [Google AI Studio](https://aistudio.google.com/app/apikey) · 기본 모델: `gemini-3.5-flash-lite` · 다른 모델 예시: `gemini-3.8-flash`, `gemini-4-argon`
- 앱의 AI 설정 창에서 권장 모델을 고르거나 모델 ID를 직접 입력할 수 있습니다. 제공자별 현재 목록은 설정 창의 `설정 가이드`에서도 확인하세요.
- 모델 ID는 바뀔 수 있으므로 실제 사용 전 공식 카탈로그를 확인하세요: [OpenAI](https://developers.openai.com/api/docs/models) · [Anthropic](https://platform.claude.com/docs/en/models/overview) · [Gemini](https://ai.google.dev/gemini-api/docs/models)
- 목업 모드는 외부 AI 요청 없이 동작하며 비용이 발생하지 않습니다. 실제 제공자 선택 후 연결 테스트나 앱 처리를 실행하면 API 사용량에 따라 비용이 발생할 수 있습니다.
- 실제 회사 자료나 개인정보는 외부 AI 제공자에 보내지 마세요. API 키는 설정 파일이 아닌 OS 자격 증명 저장소에 보관합니다.

## 개발 실행

Python 3.12 이상이 필요합니다.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe scripts\create_mock_workbooks.py
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q
Remove-Item Env:QT_QPA_PLATFORM
.\.venv\Scripts\python.exe -m hospital_marketing.app
```

실제 Gemini 연결은 별도 live 테스트로 확인합니다. 저장소 루트에 `.env.example`을 복사해 `.env`로 만들고 `GEMINI_API_KEY=`에 테스트 키를 입력하거나 `GEMINI_API_KEY` 환경 변수를 설정한 뒤 실행하세요. `.env`는 테스트 전용이며 앱 설정에는 사용하지 않습니다. 기본 테스트에서는 live 테스트를 제외합니다.

```powershell
.\.venv\Scripts\python.exe -m pytest -m live -q
```

목업 입력은 다음 위치에 생성됩니다.

```text
fixtures/source/initial/
fixtures/source/weekly/
```

앱에서 Source/Target 폴더를 지정하고 읽을 확장자를 선택합니다. 선택한 폴더 바로 아래에 있는 파일만 읽고, 하위 폴더는 처리하지 않습니다. 따라서 날짜별 목업 업데이트는 `data/source/20261102`, `20261103`, `20261106` 폴더를 하나씩 차례로 선택합니다. 상위 폴더 `data/source`를 선택하면 읽은 파일 0개와 병원 변경 없음이 보고서와 앱 결과에 표시됩니다.

`ContentCandidates` 시트의 제품 관련 콘텐츠를 `Scripts` 시트(`content_url`, `script_text`, `summary`, `usage_status`, `collected_at`)로 연결할 수 있습니다. `Scripts` 시트는 선택 사항이며, 활용 상태는 `미활용`·`제작 중`·`게시 완료`를 사용합니다. 스크립트가 있고 요약이 비어 있으면 설정된 AI 제공자가 요약을 제안합니다(목업 모드는 규칙 기반). 실제 YouTube·블로그에 접속해 수집하지 않습니다.

## 결과 폴더

```text
target/
├── data/app.db
├── wiki/<hospital_id>.md
├── wiki/source-documents/<relative-name>_<extension>.md
├── scripts/index.json
├── scripts/<hospital_id>/<YYYY-MM|undated>/<content>.md
├── dashboard/index.html
├── exports/marketing.xlsx
└── reports/last-import.json
```

대시보드 HTML은 브라우저에서 직접 열어 검색·제품·플랫폼 필터를 사용할 수 있습니다. 콘텐츠 제작 탭의 스크립트는 사용자가 제공한 원본 `Scripts` 시트에서 읽으며, 웹/SNS를 자동 수집하지 않습니다. `target/scripts/` 파일은 DB에서 다시 생성되는 결과물이므로 직접 편집하지 마세요(다음 실행 때 덮어씁니다). 활용 상태 변경은 원본 `Scripts` 시트를 고쳐 다시 가져옵니다. 스크립트 파일 정리는 `target/scripts/` 안에서만 이뤄집니다. 병원 콘텐츠는 저작권이 있으므로 SNS 활용 전 사전 허락과 출처 표기가 필요합니다.

결과를 공유하려면 HTML 파일 또는 target 폴더를 전달합니다.

## Windows EXE 만들기

Windows 환경에서 Python 3.12 이상을 설치한 뒤 PowerShell에서 실행합니다.

```powershell
.\scripts\package_windows.ps1
```

생성 경로: `dist-win\HospitalMarketingMVP\HospitalMarketingMVP.exe`

Windows EXE는 Windows에서 빌드해야 합니다. WSL의 Linux 빌드 결과는 Windows EXE가 아닙니다. 패키징 후 실행해 source/target 폴더 선택, 목업 가져오기, 대시보드 열기까지 확인하세요.

## 에이전트 협업

wsl-hermes(개발) → wsl-claude(검토·main merge) → windows-claude(Windows 테스트) 흐름과 역할별 절차는 [AGENTS.md](AGENTS.md)에 있습니다.

## 실행 파일 받기

Windows 실행 파일(EXE)은 저장소에 포함하지 않고 [GitHub Releases](https://github.com/youtaeyeon/-legacy-data-workbench/releases)에 zip으로 올립니다. zip을 풀고 `HospitalMarketingMVP\HospitalMarketingMVP.exe`를 실행하세요.
