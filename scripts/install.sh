#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${WILLY_REPO_URL:-https://github.com/gabrsar/willy.git}"
INSTALL_DIR="${WILLY_INSTALL_DIR:-$HOME/.local/share/willy}"
BIN_DIR="${WILLY_BIN_DIR:-$HOME/.local/bin}"

info() {
  printf '%s\n' "$*"
}

need() {
  if ! command -v "$1" >/dev/null 2>&1; then
    info "Missing required command: $1"
    info "Install $1, then run this installer again."
    exit 1
  fi
}

need git
need python3

mkdir -p "$BIN_DIR"

if [ -d "$INSTALL_DIR/.git" ]; then
  info "Updating Willy in $INSTALL_DIR"
  git -C "$INSTALL_DIR" pull --ff-only
else
  info "Installing Willy into $INSTALL_DIR"
  rm -rf "$INSTALL_DIR"
  git clone "$REPO_URL" "$INSTALL_DIR"
fi

info "Creating virtualenv"
python3 -m venv "$INSTALL_DIR/.venv"

info "Installing Willy"
"$INSTALL_DIR/.venv/bin/python" -m pip install --upgrade pip
"$INSTALL_DIR/.venv/bin/python" -m pip install -e "$INSTALL_DIR"

ln -sf "$INSTALL_DIR/.venv/bin/willy" "$BIN_DIR/willy"

info ""
info "Willy installed."
info ""
info "Run:"
info "  willy --help"
info "  willy setup"
info ""
info "If willy is not found, add this to your shell config:"
info "  export PATH=\"\$HOME/.local/bin:\$PATH\""
