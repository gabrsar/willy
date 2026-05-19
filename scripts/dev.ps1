param(
    [ValidateSet("setup", "install", "lint", "test", "run", "tray", "build-exe", "stop", "hooks", "clean")]
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
$PyInstallerExe = Join-Path $ScriptsDir "pyinstaller.exe"
$IconPng = Join-Path $RepoRoot "assets\\icon.png"
$IconIco = Join-Path $RepoRoot "assets\\icon.ico"

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

    $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText((Join-Path $hooksDir "pre-commit"), $preCommit, $Utf8NoBom)
    [System.IO.File]::WriteAllText((Join-Path $hooksDir "pre-push"), $prePush, $Utf8NoBom)
}

function Clean-Artifacts {
    Remove-Item -LiteralPath (Join-Path $RepoRoot ".pytest_cache") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $RepoRoot "build") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $RepoRoot "dist") -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $RepoRoot "WillyTray.spec") -Force -ErrorAction SilentlyContinue
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
        "tray" {
            Ensure-Venv
            & $WillyExe statusbar
        }
        "build-exe" {
            Ensure-Venv
            if ((Test-Path $IconPng) -and -not (Test-Path $IconIco)) {
                & $PythonExe -c "from PIL import Image; Image.open(r'$IconPng').save(r'$IconIco', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
            }
            $args = @(
                "--noconfirm",
                "--clean",
                "--onedir",
                "--windowed",
                "--name",
                "WillyTray",
                "--paths",
                "src",
                "--add-data",
                "assets/icon.png;assets"
            )
            if (Test-Path $IconIco) {
                $args += @("--icon", $IconIco)
            }
            $args += ".\\src\\willy\\tray_app.py"
            & $PyInstallerExe @args
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
