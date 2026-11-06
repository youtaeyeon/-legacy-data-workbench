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

목업 입력은 다음 위치에 생성됩니다.

```text
fixtures/source/initial/
fixtures/source/weekly/
```

앱에서 Source/Target 폴더를 지정하고 읽을 확장자를 선택합니다. 초기 병원 목업 폴더와 주간 업데이트 폴더를 각각 Source로 지정해 ID 기준 증분 업데이트를 시연할 수 있습니다.

## 결과 폴더

```text
target/
├── data/app.db
├── wiki/<hospital_id>.md
├── wiki/source-documents/<relative-name>_<extension>.md
├── dashboard/index.html
├── exports/marketing.xlsx
└── reports/last-import.json
```

대시보드 HTML은 브라우저에서 직접 열어 검색·제품·플랫폼 필터를 사용할 수 있습니다. 결과를 공유하려면 HTML 파일 또는 target 폴더를 전달합니다.

## Windows EXE 만들기

Windows 환경에서 Python 3.12 이상을 설치한 뒤 PowerShell에서 실행합니다.

```powershell
.\scripts\package_windows.ps1
```

생성 경로: `dist-win\HospitalMarketingMVP\HospitalMarketingMVP.exe`

Windows EXE는 Windows에서 빌드해야 합니다. WSL의 Linux 빌드 결과는 Windows EXE가 아닙니다. 패키징 후 실행해 source/target 폴더 선택, 목업 가져오기, 대시보드 열기까지 확인하세요.

## 에이전트 협업

wsl-hermes(개발) → wsl-claude(검토·main merge) → windows-claude(Windows 테스트) 흐름과 역할별 절차는 [AGENTS.md](AGENTS.md)에 있습니다.
