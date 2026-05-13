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
2. `willy save "message"` commits unsaved profile JSON files and pushes.
3. `willy start` runs the background watcher.
4. While Orca is open, Willy watches for profile changes.
5. When changes settle, Willy auto-saves them.
6. When Orca closes, Willy does a final save and sync.

Willy uses normal Git remotes, so it can work with GitHub, GitLab, Gitea, Forgejo, Bitbucket, self-hosted Git, or a local bare repo.

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
- existing repo detection
- remote validation
- SSH key guidance
- automatic watcher scaffold
- daemon start/stop
- profile JSON detection for `default/...` and `<user_id>/...`

Still being hardened:

- conflict recovery UX
- history view
- revert/restore
- launchd integration
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
