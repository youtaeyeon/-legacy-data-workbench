#requires -Version 5.1
param([switch]$SkipDependencyInstall)
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $ProjectRoot
try {
    $PythonExe = (& py -3.12 -c "import sys; print(sys.executable)" 2>$null).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $PythonExe) {
        throw "Python 3.12 이상이 필요합니다. Python 3.12 이상을 설치한 뒤 다시 실행하세요."
    }

    $VenvDir = Join-Path $ProjectRoot ".venv-win"
    $VenvPython = Join-Path $VenvDir "Scripts\python.exe"
    if (-not (Test-Path $VenvPython)) {
        & $PythonExe -m venv $VenvDir
        if ($LASTEXITCODE -ne 0) { throw "프로젝트 전용 Python 환경을 만들지 못했습니다." }
    }

    if (-not $SkipDependencyInstall) {
        & $VenvPython -m pip install -e ".[dev]"
        if ($LASTEXITCODE -ne 0) { throw "Python 의존성 설치에 실패했습니다." }
    }

    $env:QT_QPA_PLATFORM = "offscreen"
    & $VenvPython -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "테스트가 통과하지 않아 패키징을 중단했습니다." }
    Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue

    $DistPath = Join-Path $ProjectRoot "dist-win"
    $WorkPath = Join-Path $ProjectRoot "build-win"
    & $VenvPython -m PyInstaller --noconfirm --clean --distpath $DistPath --workpath $WorkPath hospital-marketing.spec
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 패키징에 실패했습니다." }

    $Executable = Join-Path $DistPath "HospitalMarketingMVP\HospitalMarketingMVP.exe"
    if (-not (Test-Path $Executable)) { throw "EXE 파일이 생성되지 않았습니다: $Executable" }
    Write-Output "Windows 앱 생성 완료: $Executable"
}
finally {
    Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
    Pop-Location
}
