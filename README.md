# Willy

Local-first Git sync for OrcaSlicer profiles.

Willy watches your OrcaSlicer profile/config directory, saves meaningful changes as Git commits, and syncs them to any normal Git remote. It is meant to replace cloud profile syncing with something boring, inspectable, recoverable, and not tied to one vendor.

Willy is macOS-first right now. Windows and Linux are planned.

## Install

One-line install:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/gabrsar/willy/main/scripts/install.sh)"
```

The installer clones Willy into `~/.local/share/willy`, creates a virtualenv, installs the CLI, and links `willy` into `~/.local/bin`.

If your shell cannot find `willy` after install, add this to your shell config:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Manual install:

```bash
git clone https://github.com/gabrsar/willy.git
cd willy
make setup
```

## What Willy Syncs

By default, Willy watches:

```text
~/Library/Application Support/OrcaSlicer/user
```

It tracks Orca profile JSON files under both common Orca layouts:

```text
default/filament/*.json
default/machine/*.json
default/process/*.json

<user_id>/filament/*.json
<user_id>/machine/*.json
<user_id>/process/*.json
```

It intentionally ignores `.info` sidecars, temp files, caches, logs, locks, `.git`, and obvious junk. The first version keeps the tracked surface small and safe.

## How It Works

Willy treats your Orca profile directory as a Git repository.

```text
OrcaSlicer profile files
        |
        v
Willy watcher / CLI
        |
        v
local Git commits
        |
        v
your Git remote
```

The basic flow:

1. `willy setup` connects your Orca profile folder to Git.
2. Setup asks whether to enable the watcher.
3. `willy save "message"` commits unsaved profile JSON files and pushes.
4. `willy start` runs the background watcher if you did not enable it during setup.
5. While Orca is open, Willy watches for profile changes.
6. When changes settle, Willy auto-saves them.
7. When Orca closes, Willy does a final save and sync.

Willy uses normal Git remotes, so it can work with GitHub, GitLab, Gitea, Forgejo, Bitbucket, self-hosted Git, or a local bare repo.

## Privacy

Some Orca printer profiles can include connection details such as `print_host`, `printhost_apikey`, tokens, passwords, or other secret-like fields.

Willy's default is conservative:

- private repo: sensitive fields are kept in commits
- public repo: sensitive fields are redacted before Git stores them
- unknown repo privacy: sensitive fields are redacted before Git stores them

This redaction happens through a local Git clean filter. Your real Orca files are not modified, so OrcaSlicer still keeps the printer data it needs on your machine.

Git itself can validate that Willy can talk to a remote, but it cannot prove whether that remote is public or private. During setup, Willy asks and stores your answer. You can also be explicit:

```bash
willy setup --private-repo
willy setup --public-repo
```

Use `--private-repo` only for a repository you trust to store printer IPs and API keys.

If you choose `--private-repo`, treat the repository as permanently sensitive:

```text
THIS REPOSITORY MUST NOT BECOME PUBLIC.
```

It may contain printer IPs, device IDs, API keys, tokens, or other sensitive OrcaSlicer printer data. Making it public later can expose secrets that were already committed in Git history.

## First Setup

Close OrcaSlicer before setup. Willy refuses setup while Orca is open so it does not race profile writes.

Use an existing profile repo:

```bash
willy setup
```

If Willy finds an existing Git repo in your Orca profile directory, it asks:

```text
Use this Git repo as Willy's default? [Y/n]
```

The default is yes.

Create/connect a new repo:

```bash
willy setup --mode new --remote git@github.com:you/orca-configs.git
```

Willy validates that it can talk to the remote before adopting it.

Setup also decides how to handle sensitive printer connection fields:

```text
Is this repository private? Willy only commits sensitive printer connection fields (like print_host and printhost_apikey) when the repo is private. Public or unknown repos get those fields redacted before Git stores them. [y/N]
```

At the end of setup, Willy asks whether to enable the watcher:

```text
Enable Willy watcher? It runs in the background, watches Orca profile changes, auto-saves after changes settle, and syncs again when Orca closes. [Y/n]
```

The default is yes. To opt out:

```bash
willy setup --no-watcher
```

If you need an SSH key:

```bash
willy setup --mode new --remote git@github.com:you/orca-configs.git --generate-ssh-key
```

Willy prints the public key and tells you to add it to your Git host.

Optional whale nonsense, standard license:

```bash
willy setup --mode new --protect-from-bamboo-poachers
```

This adds AGPL-3.0 protection assets. It does not create a custom license.

## Daily Use

Show sync health:

```bash
willy status
```

Status shows:

- whether Orca is running
- watched directory
- repo path
- branch and remote
- sensitive field policy
- unsaved config count
- preview of unsaved config paths
- daemon status
- next automatic save
- last commit
- last sync

Manually save and push:

```bash
willy save "tuned ABS and PETG profiles"
```

`willy save` always syncs. If there are no new changes, it still pushes/pulls when a remote exists.

Start automatic saving:

```bash
willy start
```

Start the macOS status bar icon:

```bash
willy statusbar
```

The status bar item appears while OrcaSlicer is running, or while Willy has profile changes or Git sync work pending. It shows:

- `W` when there are no pending changes
- `W*` when Willy sees pending profile changes or sync/download work
- `W...` while Willy is saving

Click it to see current status, open a detailed status window, force sync/download, or enable/disable daemon startup at login.

If you disable daemon startup, Willy will warn you that automatic syncing will not start after login. You will need to run:

```bash
willy start
```

Stop automatic saving:

```bash
willy stop
```

Watch logs:

```bash
tail -f ~/.willy/logs/events.jsonl
```

## Important Commands

```text
willy setup      Connect OrcaSlicer profiles to Git
willy start      Start automatic syncing
willy stop       Stop automatic syncing
willy statusbar  Show macOS status bar sync controls
willy save       Save changes with a description and push
willy status     Show sync health
willy history    Show profile history (planned)
willy revert     Restore older profile versions (planned)
```

Development commands:

```bash
make help
make setup
make lint
make test
```

## Safety Model

Willy is intentionally conservative.

- Setup refuses to run while OrcaSlicer is open.
- Setup creates backups before touching profile data.
- Bad remotes fail before config is saved or repos are mutated.
- Existing repos are detected and adopted only after confirmation.
- Remote access is validated before adoption.
- Only JSON profile/config files are staged by default.
- Sensitive printer connection fields are redacted for public or unknown repositories.
- Git errors are shown as recovery-oriented messages, not Python tracebacks.

Backups live under:

```text
~/.willy/backups
```

State and logs live under:

```text
~/.willy/config.toml
~/.willy/state.json
~/.willy/logs
```

## Current Status

Working:

- setup
- status
- manual save + push
- privacy-aware sensitive field redaction
- existing repo detection
- remote validation
- SSH key guidance
- automatic watcher scaffold
- daemon start/stop
- macOS status bar icon while OrcaSlicer is active or sync/profile work is pending
- login startup toggle for the daemon
- profile JSON detection for `default/...` and `<user_id>/...`

Still being hardened:

- conflict recovery UX
- history view
- revert/restore
- launchd recovery/status polish
- Windows/Linux support

## Uninstall

Stop the daemon first:

```bash
willy stop
```

Then remove the installed app files:

```bash
rm -rf ~/.local/share/willy
rm -f ~/.local/bin/willy
```

Willy state/backups are kept in `~/.willy`. Remove them only if you are sure:

```bash
rm -rf ~/.willy
```
