# 에이전트 작업 지침

이 저장소는 세 에이전트가 역할을 나눠 작업합니다. **작업을 시작하기 전에 아래 "내 역할 찾기"로 자신의 역할을 정하고, 그 역할의 절차만 따르세요.** 사람이 따로 설명하지 않아도 이 문서만으로 작업할 수 있어야 합니다.

## 흐름 한눈에 보기

```
고객(사용자) ──(피드백을 말로 전달)──────────────────────────▶ wsl-claude(PM)
wsl-claude ──(작업 단위 이슈 + 라벨 ready-for-dev)───────────▶ wsl-hermes
wsl-hermes ──(feat/* 푸시 + PR 생성, 라벨 needs-review)──────▶ wsl-claude
wsl-claude ──(수정 필요 → 라벨 changes-requested)─────────────▶ wsl-hermes
wsl-claude ──(검토 통과 → merge, PR에 라벨 needs-windows-test)──▶ windows-claude
windows-claude ──(실패 → 이슈, 라벨 windows-test-failed)───────▶ wsl-hermes
windows-claude ──(통과 → EXE 로컬 빌드, 라벨 ready-for-user-test, 알림)──▶ 고객
windows-claude ──(고객이 요청하면 → GitHub Releases에 zip 업로드)
```

에이전트끼리의 신호는 모두 **GitHub PR·이슈·라벨**로 주고받습니다. 저장소: `youtaeyeon/-legacy-data-workbench`

사용자는 **고객**이고, `wsl-claude`가 **PM**입니다. 고객 피드백은 `wsl-claude`가 이슈로 정리하고, 개발 순서를 `ready-for-dev` 라벨로 정합니다. 각 역할은 아래 "자동 실행"에 따라 10분마다 자기 차례의 라벨만 확인해서 처리합니다.

## 내 역할 찾기

| 역할 | 누구 | 작업 폴더 | 하는 일 |
|---|---|---|---|
| `wsl-hermes` | WSL Ubuntu의 Hermes Agent | `~/hospital-marketing-mvp` | 기능 개발, 버그 수정 |
| `wsl-claude` | WSL Ubuntu의 Claude Code | `~/hospital-marketing-mvp-review` | PM(이슈 작성·우선순위), PR 검토, main merge |
| `windows-claude` | Windows의 Claude Code | `C:\work\hospital-marketing-mvp` | main pull 후 Windows 테스트 |

- 내가 Hermes면 → `wsl-hermes`
- 내가 Claude Code이고 Linux(WSL)에서 실행 중이면 → `wsl-claude`
- 내가 Claude Code이고 Windows에서 실행 중이면 → `windows-claude`
- 지금 폴더가 내 역할의 작업 폴더와 다르면 파일을 고치지 말고, 사용자에게 올바른 폴더에서 실행해 달라고 알리세요.

## 모든 역할 공통 규칙

1. **main에 직접 커밋·푸시 금지.** main은 `wsl-claude`가 PR merge(`gh pr merge`)로만 바꿉니다. 유일한 예외는 사용자가 직접 지시한 경우입니다.
2. **다른 역할의 작업 폴더를 수정하지 않습니다.** 같은 Ubuntu 사용자라 접근은 되지만 건드리지 않습니다.
3. **실제 회사 자료, API 키, 개인 연락처는 커밋하지 않습니다.** 테스트는 목업 데이터만 씁니다. API 키는 OS 자격 증명 저장소에만 둡니다.
4. 브랜치 이름: `feat/<주제>`, `fix/<주제>`, `test/<주제>`, `docs/<주제>`, `chore/<주제>`. 영문 소문자와 하이픈만 씁니다.
5. 커밋 메시지는 한국어나 영어로 무엇을 왜 바꿨는지 한 줄로 씁니다. 커밋 하나에는 관련된 변경만 담습니다.
6. 테스트가 실패한 상태로 PR을 열거나 merge하지 않습니다.
7. 쓰는 라벨은 아래 "자동 실행"의 라벨 표에 있습니다.
8. **`gh pr edit --add-label/--remove-label`은 이 저장소에서 오류가 납니다**(Projects classic 지원 종료). 라벨은 REST로 바꿉니다. 이슈와 PR 모두 같은 명령입니다.
   ```bash
   gh api repos/youtaeyeon/-legacy-data-workbench/issues/<번호>/labels -f 'labels[]=<추가할 라벨>'
   gh api -X DELETE repos/youtaeyeon/-legacy-data-workbench/issues/<번호>/labels/<지울 라벨>
   ```

## 자동 실행 (10분 간격)

각 역할은 스케줄러로 10분마다 아래 순서로 실행합니다.
1. **먼저 셸에서 `gh`로 할 일이 있는지만 확인합니다.** 없으면 AI 세션을 띄우지 않고 바로 끝냅니다. 할 일이 없을 때 AI 사용량은 0이어야 합니다.
2. **잠금:** 같은 역할의 이전 실행이 아직 돌고 있으면 건너뜁니다(Linux `flock`, Windows 잠금 파일). 잠금이 2시간 넘게 남아 있으면 로그에 경고를 남깁니다.
3. 할 일이 있으면 AI 세션을 실행해 **한 번에 한 건만** 처리하고 끝냅니다.
4. 실행 기록은 각자 로컬 로그 파일에 남기고, git에는 커밋하지 않습니다.
5. `needs-human` 라벨이 붙은 이슈·PR은 아무 역할도 자동으로 처리하지 않습니다.

### 라벨 표

| 라벨 | 붙이는 쪽 | 가져가는 쪽 | 뜻 |
|---|---|---|---|
| `ready-for-dev` | wsl-claude | wsl-hermes | 개발해도 되는 이슈 |
| `in-progress` | 작업을 시작한 역할 | — | 작업 중 표시. 끝나면 직접 뗍니다 |
| `needs-review` | wsl-hermes | wsl-claude | 검토할 PR |
| `changes-requested` | wsl-claude | wsl-hermes | 고칠 점이 있는 PR |
| `needs-windows-test` | wsl-claude(merge 직후 PR에) | windows-claude | Windows 테스트 대기 |
| `windows-test-failed` | windows-claude(이슈에) | wsl-hermes | Windows 테스트 실패 |
| `ready-for-user-test` | windows-claude(PR에) | 고객 | 고객이 EXE로 확인할 차례 |
| `needs-human` | 누구나 | 사람 | 자동 처리 중단. 고객이나 PM이 확인합니다 |

### 역할별 확인 명령과 처리 순서

- **wsl-hermes:** 위에서부터 첫 번째로 해당하는 한 건만 처리합니다.
  1. `gh issue list --state open --label windows-test-failed`
  2. `gh pr list --state open --label changes-requested`
  3. `in-progress` 라벨이 붙은 열린 이슈가 없을 때만: `gh issue list --state open --label ready-for-dev`에서 **번호가 가장 작은** 이슈
  - 이슈를 시작하면 `ready-for-dev`를 떼고 `in-progress`를 붙입니다. PR을 열면 그 이슈의 `in-progress`를 뗍니다.
- **wsl-claude:** `gh pr list --state open --label needs-review`에서 번호가 가장 작은 PR 한 건을 검토합니다.
- **windows-claude:** `gh pr list --state merged --label needs-windows-test`가 있으면 최신 main을 **한 번** 테스트하고, 결과를 그 PR들에 함께 반영합니다.

### 무한 반복 방지

- 같은 PR에 wsl-claude의 수정 요청이 **3번째**가 되면, 더 요청하지 않고 `needs-human`을 붙인 뒤 이유를 댓글로 남깁니다.
- 같은 문제로 `windows-test-failed` 이슈가 **3번째** 생기면, 새로 만들지 않고 기존 이슈에 `needs-human`을 붙입니다.
- 작업 도중 판단할 수 없는 문제(요구사항이 모호함, 외부 계정이나 결제가 필요함, 다른 역할의 폴더를 고쳐야 함)를 만나면, 추측해서 진행하지 말고 `needs-human`과 함께 질문을 댓글로 남깁니다.

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
- **source 폴더 규칙:** 앱은 선택한 폴더 **바로 아래** 파일 중 선택한 확장자만 읽습니다. 하위 폴더는 읽지 않습니다. 매번 바뀐 파일이 있는 폴더를 source로 지정하는 것이 정상 사용 방식입니다(이슈 #9). 이 동작을 재귀 탐색으로 되돌리지 마세요.
  - 날짜별 목업은 세 폴더를 **날짜순으로 하나씩** source로 지정합니다. 상위 폴더 `data/source`를 선택하면 읽은 파일 0개, 병원 변화 없음이 정상입니다.
  - 기대 결과: 신규 14 → 신규 3 + 변경 없음 14 → 신규 4 + 변경 없음 17. `tests/test_sample_source_data.py`가 이 결과를 검증합니다.
- `data/목업 자료.xlsx`: 영업부·마케팅부 시트의 원래 예시 자료입니다. importer가 직접 읽는 형식이 아니라 참고용입니다.
- importer가 읽는 형식: `Hospitals` 시트, 1행 영문 헤더, `hospital_id`와 `hospital_name` 필수. 보강 시트는 `Deliveries`, `Materials`, `Channels`, `ContentCandidates`입니다.

---

## 역할: wsl-hermes (개발)

작업 폴더: `~/hospital-marketing-mvp`

### 작업 시작 전
1. `git fetch origin && git switch main && git pull --ff-only`
2. 처리할 일은 위 "자동 실행"의 wsl-hermes 순서대로 한 건만 고릅니다. `ready-for-dev`가 없는 이슈는 시작하지 않습니다(PM이 아직 승인하지 않은 일).

### 새 작업
1. 이슈에서 `ready-for-dev`를 떼고 `in-progress`를 붙인 뒤, main에서 `git switch -c feat/<주제>` (버그는 `fix/<주제>`)
2. 구현과 함께 테스트를 추가하거나 고칩니다. 동작을 바꾸는 변경에는 테스트가 있어야 합니다.
3. 전체 테스트를 통과시킵니다(위 WSL 테스트 명령).
4. 커밋하고 `git push -u origin <브랜치>`
5. PR을 엽니다.
   ```bash
   gh pr create --base main --label needs-review --title "<요약>" --body "<무엇을/왜/어떻게 테스트했는지, 관련 이슈가 있으면 Fixes #번호>"
   ```
6. 이슈의 `in-progress`를 뗍니다. 새로 만든 파일이 untracked로 빠지지 않았는지 `git status`로 확인합니다. **직접 merge하지 않습니다.** 검토는 wsl-claude가 자동으로 가져갑니다.

### 검토 의견 반영 (`changes-requested`)
1. `gh pr view <번호> --comments`로 지적 사항을 읽습니다.
2. 같은 브랜치에서 고치고 테스트한 뒤 푸시합니다.
3. 라벨을 바꿉니다: `changes-requested`를 떼고 `needs-review`를 붙입니다(공통 규칙 8의 REST 명령).
4. PR에 무엇을 고쳤는지 댓글을 남깁니다.

### 릴리스용 버전 올리기
사용자가 새 릴리스를 요청했는데 `pyproject.toml`의 `version`이 이미 릴리스된 버전(`gh release list`)이면, `chore/bump-version-<새 버전>` 브랜치에서 `version`을 올리는 PR을 엽니다. 작은 수정은 패치(0.1.0 → 0.1.1), 기능 추가는 마이너(0.1.0 → 0.2.0)를 올립니다. merge되면 `windows-claude`가 릴리스합니다.

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
     merge한 뒤 PR에서 `needs-review`를 떼고 `needs-windows-test`를 붙입니다. 이제 `windows-claude`가 테스트할 차례입니다.
   - **수정 필요:** `gh pr comment <번호> --body "wsl-claude 리뷰: 수정 요청 …(파일:줄 단위 지적 사항)"`을 남기고, `needs-review`를 떼고 `changes-requested`를 붙입니다. 이번이 이 PR의 3번째 수정 요청이면 `needs-human`을 붙입니다.

### PM 업무
- 고객이 말한 피드백은 작업 단위로 나눠 이슈를 만듭니다. 각 이슈에는 현상, 요구사항, 테스트 기준을 적습니다.
- 개발할 순서가 된 이슈에만 `ready-for-dev`를 붙입니다. 급한 이슈는 번호가 작지 않아도, 다른 이슈의 `ready-for-dev`를 잠시 떼서 먼저 하게 합니다.
- `needs-human`이 붙은 항목은 고객에게 알리고, 결정이 나면 라벨을 정리합니다.
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

GitHub CLI(`gh`)가 없으면 설치합니다. PR 댓글, 이슈 생성, 릴리스 업로드에 필요합니다.
```powershell
winget install --id GitHub.cli -e
```
설치한 뒤 **사용자에게** 새 PowerShell 창에서 `gh auth login`을 직접 실행해 달라고 요청합니다. 브라우저 로그인이 필요해서 에이전트가 대신할 수 없습니다. `gh auth status`로 로그인을 확인합니다.

### main이 바뀔 때마다
1. `git fetch origin`. `git rev-parse HEAD`와 `git rev-parse origin/main`이 같으면 "새 변경 없음"이라고 알리고 끝냅니다.
2. `git switch main; git pull --ff-only`
3. 의존성이 바뀌었을 수 있으니 `.\.venv\Scripts\python.exe -m pip install -e ".[dev]"`
4. 전체 테스트를 실행합니다(위 Windows 테스트 명령).
5. 앱 실행 확인: `.\.venv\Scripts\python.exe -m hospital_marketing.app`를 실행해 창이 뜨는지 봅니다. 사용자가 함께 있으면 `data\source\20261102` → `20261103` → `20261106`을 차례로 가져와 대시보드를 열어 달라고 요청합니다.
6. 사용자가 EXE 확인을 원하면 `.\scripts\package_windows.ps1`로 빌드하고 `dist-win\HospitalMarketingMVP\HospitalMarketingMVP.exe`를 실행합니다.
7. 결과를 보고합니다. 대상은 `needs-windows-test` 라벨이 붙은 merge된 PR 전부입니다.
   - **성공:** 각 PR에 `Windows 테스트 통과 (<커밋 해시>): pytest N개 통과, 앱 실행 확인, PR별 확인 항목` 댓글을 남깁니다. 그다음 `scripts\package_windows.ps1`로 EXE를 **로컬에만** 빌드합니다(릴리스하지 않음). 각 PR에서 `needs-windows-test`를 떼고 `ready-for-user-test`를 붙입니다. 마지막으로 Windows 알림(토스트)으로 고객에게 "테스트할 EXE 준비됨: <EXE 경로>, <PR 목록>"을 알립니다.
   - **실패:** 이슈를 만들고, 원인이 된 PR에서 `needs-windows-test`를 뗍니다.
     ```powershell
     gh issue create --label windows-test-failed --title "Windows 테스트 실패: <요약>" --body "<커밋 해시, 관련 PR, 실패한 명령, 오류 로그 핵심 부분, 재현 방법>"
     ```
     코드는 직접 고치지 않습니다. 수정은 `wsl-hermes`가 합니다.
   - 자동 실행 중에는 사용자 조작이 필요한 단계(5단계의 데이터 가져오기 요청 등)를 건너뜁니다. 대신 UI Automation이나 offscreen으로 확인할 수 있는 만큼만 확인합니다.
8. 이 폴더에서는 커밋하거나 푸시하지 않습니다. 아래 릴리스 절차의 `gh release create`(태그 생성)만 예외입니다.

### 릴리스 (EXE 배포)

EXE와 빌드 결과물(`dist-win/`, `build-win/`)은 git에 커밋하지 않습니다(`.gitignore`). 제출이나 배포용 EXE는 **GitHub Releases**에 zip으로 올립니다.

**언제:** 사용자가 "릴리스/배포/제출용 EXE 만들어 줘"라고 요청할 때만 합니다. main이 바뀔 때마다 자동으로 하지 않습니다.

**버전 규칙:** 태그는 `v<pyproject.toml의 version>`입니다(예: `v0.1.0`). 같은 버전은 한 번만 릴리스합니다. 버전을 올리는 것은 `wsl-hermes`가 PR로 합니다.

1. 위 "main이 바뀔 때마다" 1~5단계를 먼저 끝내서, 최신 main에서 Windows 테스트가 통과한 상태여야 합니다. 실패했다면 릴리스하지 않고 이슈를 만듭니다.
2. 버전과 커밋을 확인합니다.
   ```powershell
   $Version = (.\.venv\Scripts\python.exe -c "import tomllib;print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])").Trim()
   $Tag = "v$Version"
   $Commit = (git rev-parse HEAD).Trim()
   gh release view $Tag 2>$null; if ($LASTEXITCODE -eq 0) { "이미 $Tag 릴리스가 있음" }
   ```
   이미 같은 태그가 있으면 멈추고, 사용자에게 "버전을 올리는 PR이 먼저 필요하다(wsl-hermes 작업)"고 알립니다. 기존 릴리스를 지우거나 덮어쓰지 않습니다.
3. 빌드합니다. 이 스크립트가 테스트도 다시 실행하고, 실패하면 중단합니다.
   ```powershell
   .\scripts\package_windows.ps1
   ```
4. 빌드한 EXE를 직접 실행해 창이 뜨는지 확인합니다: `dist-win\HospitalMarketingMVP\HospitalMarketingMVP.exe`
5. 폴더째 zip으로 묶습니다. EXE 혼자서는 실행되지 않고 `_internal\` 폴더가 함께 있어야 합니다.
   ```powershell
   $Zip = "dist-win\HospitalMarketingMVP-$Tag-win64.zip"
   Compress-Archive -Path dist-win\HospitalMarketingMVP -DestinationPath $Zip -Force
   ```
6. 릴리스를 만듭니다.
   ```powershell
   gh release create $Tag $Zip --target $Commit --title "HospitalMarketingMVP $Tag" --notes "Windows 64bit 실행 파일. zip을 풀고 HospitalMarketingMVP\HospitalMarketingMVP.exe를 실행하세요. 빌드 커밋: $Commit. 테스트용 원본 데이터는 저장소의 data\source 폴더에 있습니다."
   ```
7. 사용자에게 릴리스 URL(`gh release view $Tag --web` 또는 `--json url`)과 zip 크기를 알립니다.
