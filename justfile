set dotenv-load := false

os := "linux"
image := "willy-dev-" + os
dockerfile := "deps/docker/Dockerfile." + os

default:
    just --list

setup:
    python -m venv .venv
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -e '.[dev]'

setup-windows:
    powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 setup

lint:
    .venv/bin/ruff check --fix src tests
    .venv/bin/ruff format src tests
    .venv/bin/ruff check src tests

lint-windows:
    powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 lint

test:
    .venv/bin/pytest

test-windows:
    powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 test

build-windows-exe:
    powershell -ExecutionPolicy Bypass -File scripts/dev.ps1 build-exe

run:
    .venv/bin/willy start

stop:
    .venv/bin/willy stop

build-docker os=os:
    docker build -f deps/docker/Dockerfile.{{os}} -t willy-dev-{{os}} .

test-docker os=os:
    docker build -f deps/docker/Dockerfile.{{os}} -t willy-dev-{{os}} .
    docker run --rm willy-dev-{{os}}

shell-docker os=os:
    docker build -f deps/docker/Dockerfile.{{os}} -t willy-dev-{{os}} .
    docker run --rm -it -v "$PWD:/workspace" -w /workspace willy-dev-{{os}} bash

shell-docker-windows:
    docker build -f deps/docker/Dockerfile.windows -t willy-dev-windows .
    docker run --rm -it -v "%cd%:C:/workspace" -w C:/workspace willy-dev-windows powershell
