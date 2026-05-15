param(
    [ValidateSet("setup", "install", "lint", "test", "run", "stop", "hooks", "clean")]
    [string]$Task = "setup"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$VenvDir = Join-Path $RepoRoot ".venv"
$ScriptsDir = Join-Path $VenvDir "Scripts"
$PythonExe = Join-Path $ScriptsDir "python.exe"
$PytestExe = Join-Path $ScriptsDir "pytest.exe"
$RuffExe = Join-Path $ScriptsDir "ruff.exe"
$WillyExe = Join-Path $ScriptsDir "willy.exe"

function Ensure-Venv {
    if (-not (Test-Path $PythonExe)) {
        python -m venv $VenvDir
    }
}

function Install-Env {
    Ensure-Venv
    & $PythonExe -m pip install --upgrade pip
    & $PythonExe -m pip install -e '.[dev]'
}

function Install-Hooks {
    if (-not (Test-Path (Join-Path $RepoRoot ".git"))) {
        git init $RepoRoot | Out-Null
    }

    $hooksDir = Join-Path $RepoRoot ".git\\hooks"
    New-Item -ItemType Directory -Force -Path $hooksDir | Out-Null

    $preCommit = @'
#!/bin/sh
set -eu
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 lint
if ! git diff --quiet; then
  echo "scripts/dev.ps1 lint changed files. Review and stage them, then commit again."
  exit 1
fi
'@

    $prePush = @'
#!/bin/sh
set -eu
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 test
'@

    Set-Content -Path (Join-Path $hooksDir "pre-commit") -Value $preCommit -Encoding utf8NoBOM
    Set-Content -Path (Join-Path $hooksDir "pre-push") -Value $prePush -Encoding utf8NoBOM
}

function Clean-Artifacts {
    Remove-Item -LiteralPath (Join-Path $RepoRoot ".pytest_cache") -Recurse -Force -ErrorAction SilentlyContinue
    Get-ChildItem -Path $RepoRoot -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
}

Push-Location $RepoRoot
try {
    switch ($Task) {
        "setup" {
            Install-Env
            Install-Hooks
        }
        "install" {
            Install-Env
        }
        "lint" {
            Ensure-Venv
            & $RuffExe check --fix src tests
            & $RuffExe format src tests
            & $RuffExe check src tests
        }
        "test" {
            Ensure-Venv
            & $PytestExe
        }
        "run" {
            Ensure-Venv
            & $WillyExe start
        }
        "stop" {
            Ensure-Venv
            & $WillyExe stop
        }
        "hooks" {
            Install-Hooks
        }
        "clean" {
            Clean-Artifacts
        }
    }
}
finally {
    Pop-Location
}
