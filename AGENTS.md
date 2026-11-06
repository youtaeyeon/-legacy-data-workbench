# 에이전트 작업 지침

이 저장소는 세 에이전트가 역할을 나눠 작업합니다. **작업을 시작하기 전에 아래 "내 역할 찾기"로 자신의 역할을 정하고, 그 역할의 절차만 따르세요.** 사람이 따로 설명하지 않아도 이 문서만으로 작업할 수 있어야 합니다.

## 흐름 한눈에 보기

```
wsl-hermes ──(feat/* 푸시 + PR 생성, 라벨 needs-review)──▶ wsl-claude
wsl-claude ──(검토 통과 → PR을 main에 merge)──────────────▶ windows-claude
wsl-claude ──(수정 필요 → 라벨 changes-requested)─────────▶ wsl-hermes
windows-claude ──(테스트 실패 → 이슈, 라벨 windows-test-failed)──▶ wsl-hermes
```

에이전트끼리의 신호는 모두 **GitHub PR·이슈·라벨**로 주고받습니다. 저장소: `youtaeyeon/-legacy-data-workbench`

## 내 역할 찾기

| 역할 | 누구 | 작업 폴더 | 하는 일 |
|---|---|---|---|
| `wsl-hermes` | WSL Ubuntu의 Hermes Agent | `~/hospital-marketing-mvp` | 기능 개발, 버그 수정 |
| `wsl-claude` | WSL Ubuntu의 Claude Code | `~/hospital-marketing-mvp-review` | PR 검토, main merge |
| `windows-claude` | Windows의 Claude Code | `C:\work\hospital-marketing-mvp` | main pull 후 Windows 테스트 |

- 내가 Hermes면 → `wsl-hermes`
- 내가 Claude Code이고 Linux(WSL)에서 실행 중이면 → `wsl-claude`
- 내가 Claude Code이고 Windows에서 실행 중이면 → `windows-claude`
- 지금 폴더가 내 역할의 작업 폴더와 다르면 파일을 고치지 말고, 사용자에게 올바른 폴더에서 실행해 달라고 알리세요.

## 모든 역할 공통 규칙

1. **main에 직접 커밋·푸시 금지.** main은 `wsl-claude`가 PR merge(`gh pr merge`)로만 바꿉니다. 유일한 예외는 사용자가 직접 지시한 경우입니다.
2. **다른 역할의 작업 폴더를 수정하지 않습니다.** 같은 Ubuntu 사용자라 접근은 되지만 건드리지 않습니다.
3. **실제 회사 자료, API 키, 개인 연락처는 커밋하지 않습니다.** 테스트는 목업 데이터만 씁니다. API 키는 OS 자격 증명 저장소에만 둡니다.
4. 브랜치 이름: `feat/<주제>`, `fix/<주제>`, `test/<주제>`, `docs/<주제>`. 영문 소문자와 하이픈만 씁니다.
5. 커밋 메시지는 한국어나 영어로 무엇을 왜 바꿨는지 한 줄로 씁니다. 커밋 하나에는 관련된 변경만 담습니다.
6. 테스트가 실패한 상태로 PR을 열거나 merge하지 않습니다.
7. 쓰는 라벨: `needs-review`, `changes-requested`, `windows-test-failed`. 라벨이 없으면 `gh label create <이름>`으로 만듭니다.

## 프로젝트 기본 정보

- 개요와 실행 방법: `README.md`
- 기획안: `docs/superpowers/specs/2026-11-05-hospital-marketing-mvp-design.md`
- 구현 계획: `docs/superpowers/plans/2026-11-05-hospital-marketing-mvp.md`
- Python 3.12 이상. 소스는 `src/hospital_marketing/`, 테스트는 `tests/`에 있습니다.

### 테스트 명령

```bash
# WSL
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

```powershell
# Windows PowerShell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
$env:QT_QPA_PLATFORM = "offscreen"; .\.venv\Scripts\python.exe -m pytest -q; Remove-Item Env:QT_QPA_PLATFORM
```

### 테스트용 원본 데이터

- `fixtures/source/initial`, `fixtures/source/weekly`: 자동 테스트용 기본 목업입니다. `scripts/create_mock_workbooks.py`로 생성합니다.
- `data/source/20261102`, `20261103`, `20261106`: 날짜별 계약병원 누적 목업입니다. `scripts/create_sample_contracts.py`로 생성합니다.
  - 앱에서는 이 세 폴더를 **날짜순으로 하나씩** source로 지정합니다. 상위 폴더 `data/source`를 한 번에 선택하면 병원 ID가 중복되어 모든 행을 건너뜁니다.
  - 기대 결과: 신규 14 → 신규 3 + 변경 없음 14 → 신규 4 + 변경 없음 17. `tests/test_sample_source_data.py`가 이 결과를 검증합니다.
- `data/목업 자료.xlsx`: 영업부·마케팅부 시트의 원래 예시 자료입니다. importer가 직접 읽는 형식이 아니라 참고용입니다.
- importer가 읽는 형식: `Hospitals` 시트, 1행 영문 헤더, `hospital_id`와 `hospital_name` 필수. 보강 시트는 `Deliveries`, `Materials`, `Channels`, `ContentCandidates`입니다.

---

## 역할: wsl-hermes (개발)

작업 폴더: `~/hospital-marketing-mvp`

### 작업 시작 전
1. `git fetch origin && git switch main && git pull --ff-only`
2. 처리할 일을 이 순서로 확인합니다.
   1. 라벨이 `windows-test-failed`인 열린 이슈: `gh issue list --label windows-test-failed`
   2. 라벨이 `changes-requested`인 내 PR: `gh pr list --label changes-requested`
   3. 사용자가 지시한 새 기능

### 새 작업
1. `git switch -c feat/<주제>` (버그는 `fix/<주제>`)
2. 구현과 함께 테스트를 추가하거나 고칩니다. 동작을 바꾸는 변경에는 테스트가 있어야 합니다.
3. 전체 테스트를 통과시킵니다(위 WSL 테스트 명령).
4. 커밋하고 `git push -u origin <브랜치>`
5. PR을 엽니다.
   ```bash
   gh pr create --base main --label needs-review --title "<요약>" --body "<무엇을/왜/어떻게 테스트했는지, 관련 이슈가 있으면 Fixes #번호>"
   ```
6. 사용자에게 PR 링크를 알리고 검토를 기다립니다. **직접 merge하지 않습니다.**

### 검토 의견 반영 (`changes-requested`)
1. `gh pr view <번호> --comments`로 지적 사항을 읽습니다.
2. 같은 브랜치에서 고치고 테스트한 뒤 푸시합니다.
3. 라벨을 바꿉니다: `gh pr edit <번호> --remove-label changes-requested --add-label needs-review`
4. PR에 무엇을 고쳤는지 댓글을 남깁니다.

### Windows 테스트 실패 (`windows-test-failed`)
1. 이슈 본문의 실패 로그를 읽고 `fix/<주제>` 브랜치에서 고칩니다.
2. PR 본문에 `Fixes #<이슈번호>`를 넣어 위 "새 작업" 5단계와 같이 PR을 엽니다.

---

## 역할: wsl-claude (검토와 main merge)

작업 폴더: `~/hospital-marketing-mvp-review` (main과 별도로 clone한 검토 전용 폴더)

### 검토할 PR 찾기
```bash
gh pr list --label needs-review
```
없으면 "검토할 PR 없음"이라고 알리고 끝냅니다.

### PR 하나 검토하기
1. 최신 상태로 맞춥니다: `git fetch origin && git switch --detach origin/<PR 브랜치>`
   (`gh pr checkout`도 됩니다. 이 폴더에서는 코드를 고치지 않습니다.)
2. 변경 내용을 읽습니다: `gh pr view <번호>`, `gh pr diff <번호>`
3. 전체 테스트를 실행합니다(위 WSL 테스트 명령).
4. 다음을 확인합니다.
   - 정확성: 기획안의 동작(신규·변경·변경 없음 판별, 제품 관련성 분류, 산출물 생성)을 깨지 않는가
   - 새 동작에 테스트가 있는가
   - 실제 회사 자료, API 키, 개인정보, 로컬 절대 경로가 들어가지 않았는가
   - Windows 호환성: 경로 처리(`pathlib` 사용), 인코딩(UTF-8/CP949), 줄바꿈
   - PR 범위를 벗어난 변경이 없는가
5. 판정합니다.
   - **통과:**
     ```bash
     gh pr comment <번호> --body "검토 통과: <요약>. 테스트 N개 통과."
     gh pr merge <번호> --squash --delete-branch
     ```
     merge하면 `windows-claude`가 테스트할 차례입니다. 사용자에게 merge 사실과 커밋 해시를 알립니다.
   - **수정 필요:**
     ```bash
     gh pr comment <번호> --body "<파일:줄 단위로 구체적인 지적 사항>"
     gh pr edit <번호> --remove-label needs-review --add-label changes-requested
     ```
6. 같은 GitHub 계정이라 GitHub의 정식 "Approve"는 쓸 수 없습니다. 검토 결과는 댓글로 남깁니다.

---

## 역할: windows-claude (Windows 테스트)

작업 폴더: `C:\work\hospital-marketing-mvp`
**`\\wsl.localhost\...` 경로에서 작업하지 마세요.** cmd가 UNC 경로를 지원하지 않아 가상환경과 빌드가 깨집니다.

### 처음 한 번
```powershell
git clone https://github.com/youtaeyeon/-legacy-data-workbench.git C:\work\hospital-marketing-mvp
cd C:\work\hospital-marketing-mvp
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

### main이 바뀔 때마다
1. `git fetch origin`. `git rev-parse HEAD`와 `git rev-parse origin/main`이 같으면 "새 변경 없음"이라고 알리고 끝냅니다.
2. `git switch main; git pull --ff-only`
3. 의존성이 바뀌었을 수 있으니 `.\.venv\Scripts\python.exe -m pip install -e ".[dev]"`
4. 전체 테스트를 실행합니다(위 Windows 테스트 명령).
5. 앱 실행 확인: `.\.venv\Scripts\python.exe -m hospital_marketing.app`를 실행해 창이 뜨는지 봅니다. 사용자가 함께 있으면 `data\source\20261102` → `20261103` → `20261106`을 차례로 가져와 대시보드를 열어 달라고 요청합니다.
6. 사용자가 EXE 확인을 원하면 `.\scripts\package_windows.ps1`로 빌드하고 `dist-win\HospitalMarketingMVP\HospitalMarketingMVP.exe`를 실행합니다.
7. 결과를 보고합니다.
   - **성공:** 방금 merge된 PR에 댓글을 남깁니다. `gh pr comment <번호> --body "Windows 테스트 통과 (<커밋 해시>): pytest N개 통과, 앱 실행 확인"`
   - **실패:** 이슈를 만듭니다.
     ```powershell
     gh issue create --label windows-test-failed --title "Windows 테스트 실패: <요약>" --body "<커밋 해시, 실패한 명령, 오류 로그 핵심 부분, 재현 방법>"
     ```
     코드는 직접 고치지 않습니다. 수정은 `wsl-hermes`가 합니다.
8. 이 폴더에서는 커밋하거나 푸시하지 않습니다.
