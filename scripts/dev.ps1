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

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

function Ensure-Venv {
    if (-not (Test-Path $PythonExe)) {
        Invoke-Native python -m venv $VenvDir
    }
}

function Install-Env {
    Ensure-Venv
    Invoke-Native $PythonExe -m pip install --upgrade pip
    Invoke-Native $PythonExe -m pip install -e '.[dev]'
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
            Invoke-Native $RuffExe check --fix src tests
            Invoke-Native $RuffExe format src tests
            Invoke-Native $RuffExe check src tests
        }
        "test" {
            Ensure-Venv
            Invoke-Native $PytestExe
        }
        "run" {
            Ensure-Venv
            Invoke-Native $WillyExe start
        }
        "tray" {
            Ensure-Venv
            Invoke-Native $WillyExe statusbar
        }
        "build-exe" {
            Ensure-Venv
            Remove-Item -LiteralPath (Join-Path $RepoRoot "build\\WillyTray") -Recurse -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath (Join-Path $RepoRoot "dist\\WillyTray") -Recurse -Force -ErrorAction SilentlyContinue
            if ((Test-Path $IconPng) -and -not (Test-Path $IconIco)) {
                Invoke-Native $PythonExe -c "from PIL import Image; Image.open(r'$IconPng').save(r'$IconIco', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])"
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
            Invoke-Native $PyInstallerExe @args
        }
        "stop" {
            Ensure-Venv
            Invoke-Native $WillyExe stop
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
