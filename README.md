# Willy

Willy is local-first Git sync for OrcaSlicer profiles.

Tweet version: Willy watches your OrcaSlicer profile folder, commits meaningful config changes to Git, and syncs them to your own remote so printer profiles stay inspectable, recoverable, and vendor-independent.

## Quick Start

```bash
git clone https://github.com/gabrsar/willy.git
cd willy
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
willy --help
```

Windows PowerShell:

```powershell
git clone https://github.com/gabrsar/willy.git
cd willy
powershell -ExecutionPolicy Bypass -File .\scripts\dev.ps1 setup
.\.venv\Scripts\willy.exe --help
```

## Build, Test, Run

With `just`:

```bash
just setup
just lint
just test
just run
just stop
```

Windows:

```powershell
just setup-windows
just lint-windows
just test-windows
just build-windows-exe
```

Without `just`, use `make` on macOS/Linux or `scripts/dev.ps1` on Windows.

## Docker Dev Environments

Use Docker when you do not want Python tooling installed on the host.

```bash
just test-docker linux
just test-docker macos
just test-docker windows
```

Dockerfiles live in `deps/docker/`:

```text
deps/docker/Dockerfile.linux
deps/docker/Dockerfile.macos
deps/docker/Dockerfile.windows
```

`Dockerfile.macos` is for macOS hosts, but it runs a Linux container because Docker does not provide native macOS containers. Validate macOS-only status bar behavior on macOS when changing it.

## Install

One-line install on macOS/Linux:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/gabrsar/willy/main/scripts/install.sh)"
```

Manual install:

```bash
willy setup
```

## Daily Use

```bash
willy setup
willy status
willy save "tuned ABS profile"
willy start
willy stop
```

On macOS, `willy statusbar` opens the status bar app. On Windows, the same command opens the tray app.

## What Willy Tracks

By default, Willy watches the OrcaSlicer user profile directory:

```text
macOS:   ~/Library/Application Support/OrcaSlicer/user
Windows: %APPDATA%\OrcaSlicer\user
Linux:   ~/.config/OrcaSlicer/user
```

It tracks Orca profile JSON files under `default/` and user profile folders, and can optionally track `.3mf` and `.stl` files inside configured project folders.

## Safety

- Setup refuses to run while OrcaSlicer is open.
- Setup creates backups before touching profile data.
- Public or unknown repositories get sensitive printer fields redacted before Git stores them.
- Git remotes are validated before adoption.

State, logs, and backups live under `~/.willy`.

## Project Structure

```text
src/willy/                 application code
tests/                     pytest suite
docs/architecture.md       architecture notes
docs/ai/                   AI prompts
docs/decision_records/     project decision records
ai.md                      AI agent guidelines
deps/docker/               dev Dockerfiles
justfile                   task runner
```

