SHELL := /bin/bash

PYTHON ?= python3
VENV := .venv
BIN := $(VENV)/bin
WILLY := $(BIN)/willy
PYTEST := $(BIN)/pytest
RUFF := $(BIN)/ruff

.PHONY: help setup install run stop test lint hooks clean

help:
	@printf '%s\n' \
		'Willy development commands:' \
		'' \
		'  make setup    Create/update .venv, install deps, initialize Git, install hooks' \
		'  make install  Create/update .venv and install runtime/dev deps' \
		'  make run      Start Willy background syncing via willy start' \
		'  make stop     Stop Willy background syncing via willy stop' \
		'  make test     Run the test suite' \
		'  make lint     Format and lint src/tests with Ruff' \
		'  make hooks    Install Git pre-commit and pre-push hooks' \
		'  make clean    Remove local test/cache artifacts'

setup: install hooks
	@echo "Willy dev environment is ready."

install:
	@test -d "$(VENV)" || "$(PYTHON)" -m venv "$(VENV)"
	@"$(BIN)/python" -m pip install --upgrade pip
	@"$(BIN)/python" -m pip install -e '.[dev]'

run:
	@"$(WILLY)" start

stop:
	@"$(WILLY)" stop

test:
	@"$(PYTEST)"

lint:
	@"$(RUFF)" check --fix src tests
	@"$(RUFF)" format src tests
	@"$(RUFF)" check src tests

hooks:
	@if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
		git init; \
	fi
	@mkdir -p .git/hooks
	@printf '%s\n' \
		'#!/bin/sh' \
		'set -eu' \
		'make lint' \
		'if ! git diff --quiet; then' \
		'  echo "make lint changed files. Review and stage them, then commit again."' \
		'  exit 1' \
		'fi' \
		> .git/hooks/pre-commit
	@printf '%s\n' \
		'#!/bin/sh' \
		'set -eu' \
		'make test' \
		> .git/hooks/pre-push
	@chmod +x .git/hooks/pre-commit .git/hooks/pre-push
	@echo "Installed Git hooks: pre-commit runs lint, pre-push runs tests."

clean:
	rm -rf .pytest_cache
	rm -rf build dist
	rm -f WillyTray.spec
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
