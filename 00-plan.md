# Willy Engineering Plan

## Summary

Build `willy` to work on Win/Linux/Mac (but lets start with MacOs), local-first Python CLI/daemon that turns `~/Library/Application Support/OrcaSlicer/user` into a safe Git-backed profile store. It watches OrcaSlicer profile changes while Orca runs, commits meaningful batches, and syncs with any standard Git remote when Orca exits.

Primary defaults: no GitHub API, no GitHub CLI, Git CLI only, repository root defaults to the Orca `user` directory, symlink mode only for advanced/import flows, backups before every risky operation.

## Architecture

```text
willy CLI
  |-- setup/status/history/revert/save/start/stop
  |
willy daemon
  |-- Orca process monitor
  |-- filesystem watcher
  |-- debounce/event journal
  |-- metadata extractor
  |-- Git engine
  |-- backup/recovery manager
  |-- lock manager
  |
Orca user dir <-> local Git repo <-> any Git remote
launchd LaunchAgent runs daemon
```

Components:

- CLI: beginner-friendly Typer commands, safe prompts.
- Daemon: long-running process launched manually or by launchd.
- Orca detector: `psutil` process scan for `OrcaSlicer`; fallback to `pgrep`.
- Watcher: `watchdog`/FSEvents recursive watcher on Orca `user`.
- Git engine: thin wrapper around allowed Git CLI commands only.
- Metadata extractor: path + JSON + `.info` sidecar inference.
- Backup manager: timestamped copies under `~/.willy/backups`.
- Config/state: TOML/JSON under `~/.willy/config.toml` and `~/.willy/state.json`.
- Locking: single daemon and single Git operation via lock files in `~/.willy/locks`.

## Filesystem Strategy

Default watched path: `~/Library/Application Support/OrcaSlicer/user`.

Track profile artifacts:

- `default/filament/*.json`, `*.info`
- `default/machine/*.json`, `*.info`
- `default/process/*.json`, `*.info`
- other user profile/config files unless ignored

Ignore:

- temp files, lock files, `.DS_Store`, editor swap files, caches, logs, partial downloads, Git internals.

Setup behavior:

- Refuse setup if OrcaSlicer is running, ask user to save everything and close orca to avoid data loss and create the first version.
- Create backup before touching the profile directory.
- Prefer in-place `git init` inside Orca `user`.
- If cloning existing repo, clone to temp, validate, back up current `user`, then merge/copy safely into final repo path with conflict prompts.


## Git Synchronization

Automatic commit flow:

- Watcher records created/modified/deleted/renamed events.
- Debounce until quiet, then run a status scan.
- Stage only allowed profile files.
- Skip commit if Git diff is empty.
- Commit message:
  `<change_type> | <profile_type> | <printer_name> | <filament_type> | <relative_path>`
- Commit body includes Printer, Filament, Profile-Type, Event, Path when known.

Sync-on-close flow:

- Detect Orca exit.
- Stop watcher.
- Run final full scan.
- Commit remaining changes.
- `git pull --rebase`.
- If clean, `git push`.
- If conflict, abort rebase when possible, preserve backups, print recovery instructions, never overwrite silently.

Manual commands:

- `willy save "description"` commits current changes with user description in body.
- `willy history` wraps `git log` with metadata grouping.
- `willy revert` previews restore, backs up first, then restores selected commit/files.

## Metadata Extraction

Precedence:

1. Path category: `filament`, `machine`, `process`.
2. JSON fields: `name`, `filament_settings_id`, `printer_settings_id`, `print_settings_id`, `inherits`, `from`.
3. `.info` sidecar IDs and timestamps.
4. Filename heuristics for material names like PLA, PETG, ABS, TPU, ASA.
5. Unknown-safe fallback: `unknown`.

Profile type mapping:

- `default/filament` -> `filament`
- `default/machine` -> `machine`
- `default/process` -> `process`
- other -> `config`

Printer family inference should be best-effort only. Never block commit or sync because metadata cannot be inferred.

## Safety Guarantees

- Backup before setup, clone/import, revert, conflict recovery, symlink changes, and destructive restore.
- Never delete without backup.
- Never overwrite on merge conflict.
- Refuse concurrent daemon instances.
- Refuse risky Git operations when repo is dirty unless the operation first commits or backs up.
- Secret avoidance: only track the Orca `user` profile tree by default; deny obvious private keys, tokens, env files, and non-profile credentials. If you track only jsons should be enough.

## CLI UX

Help starts with:

```text
TL;DR:
setup Connect OrcaSlicer profiles to Git
start Start automatic syncing
stop Stop automatic syncing
save Save changes with a description
revert Restore an older profile version
status Show sync health
```

Commands:

- `willy setup [--protect-from-bamboo-poachers] [--dry-run]`
- `willy start`
- `willy stop`
- `willy save "description"`
- `willy status`
- `willy history [--printer X] [--filament X] [--profile-type X] [--since DATE]`
- `willy revert [--commit SHA] [--path PATH] [--dry-run]`
- `willy help advanced`

Setup flow:

- Detect Git installation.
- If missing, guide macOS installation with `xcode-select --install`; mention Homebrew only when available.
- Locate Orca profile directory.
- Refuse setup while Orca runs.
- Create timestamped backup.
- Ask existing repo vs new local repo.
- Ask remote URL when needed.
- Validate remote with Git/SSH.
- If SSH key missing, offer `ssh-keygen -t ed25519`, print public key, explain GitHub/GitLab/Gitea setup.
- If new repo and protection enabled, add AGPL-3.0 LICENSE and README joke section.
- Offer launchd integration.

## Daemon And launchd

Daemon lifecycle:

- Start idle.
- Poll for Orca process.
- On launch: acquire repo lock, snapshot baseline, start watcher.
- During run: debounce and auto-commit.
- On exit: final scan, commit, pull-rebase, push, release lock.
- On error: log, preserve state, continue unless repo safety is uncertain.

launchd:

- Generate `~/Library/LaunchAgents/com.willy.sync.plist`.
- Runs `willy daemon`.
- `willy start` loads/starts agent.
- `willy stop` unloads agent and stops daemon gracefully.
- Status reports launchd loaded/running state.

## Logging And Debugging

Logs:

- Human log: `~/.willy/logs/willy.log`
- JSON event log: `~/.willy/logs/events.jsonl`
- Last sync summary in state file.

Log events:

- setup steps, backups, process transitions, watcher batches, commits, pull/push results, conflicts, skipped files, errors.

Example:

```text
2026-05-13T14:32:11-03:00 INFO commit path=default/process/my_abs_fast.json type=process material=ABS
2026-05-13T14:40:02-03:00 WARN sync_conflict action=backup_and_abort backup=~/.willy/backups/...
```

## Example Config

```toml
orca_user_dir = "~/Library/Application Support/OrcaSlicer/user"
repo_path = "~/Library/Application Support/OrcaSlicer/user"
remote = "git@github.com:user/orca-profiles.git"
branch = "main"
debounce_seconds = 3
max_batch_seconds = 30
protect_from_bamboo_poachers = true
launchd_enabled = true
```

## Example Repo Layout

```text
orca-profiles/
  .gitignore
  LICENSE
  README.md
  default/
    filament/
    machine/
    process/
  hints.cereal
```

README protection section uses AGPL-3.0 only:

```text
Protected Orca

This repository is protected from bamboo poachers.

Powered by:
OrcaSlicer
Git
stubborn independence
```

## Testing Strategy

Unit tests:

- Metadata extraction from paths, JSON, `.info`, bad JSON, unknown files.
- Ignore rules.
- Commit message/body generation.
- Config loading and idempotent setup decisions.

Integration tests:

- Temp Orca profile tree + real Git repo.
- Create/modify/delete/rename detection.
- Debounced commits.
- Pull-rebase/push against local bare remote.
- Dirty repo and conflict handling.
- Revert preview and restore with backup.

macOS/manual tests:

- launchd install/start/stop.
- Orca running detection.
- Symlink mode.
- SSH key guidance flow.

## Failure And Recovery Scenarios

- Git missing: guide install, do not proceed silently.
- Remote inaccessible: keep local commits, show SSH/remote fix steps.
- Rebase conflict: abort or pause safely, create backup, print exact commands.
- Orca open during setup/revert: refuse and explain.
- Duplicate daemon: second process exits with lock owner info.
- Corrupt JSON: commit as file change, metadata becomes unknown.
- Backup restore: `willy revert` lists backups and recent commits, previews changed paths, backs up current state before restore.

## Implementation Phases

1. Package skeleton, config, logging, Git wrapper, status command.
2. Setup flow, backups, Git init/remote validation, SSH help.
3. Metadata extraction and commit formatting.
4. Watch daemon, debounce, auto-commit.
5. Sync-on-close with pull-rebase/push and conflict safety.
6. History/revert UX.
7. launchd integration.
8. Hardening: dry-run, tests, docs, release packaging.

## Recommended Tools

- Python 3.11+
- `typer` for CLI
- `watchdog` for macOS FSEvents
- `psutil` for Orca detection
- `platformdirs` for state paths
- `filelock` or `portalocker` for locks
- Standard Git CLI only
- Bash only for tiny install/helper scripts

## Risks And Tradeoffs

- Auto-commits may be noisy; debounce plus final close commit keeps history usable.
- Git conflicts cannot be made invisible safely; design favors explicit recovery.
- Orca file formats may evolve; metadata inference must remain best-effort.
- Git remote creation cannot be automated without provider APIs; setup should instruct users to create an empty remote when needed.

## Future Ideas

- Profile visual diffing.
- Timeline/history UI.
- Restore UI.
- Local web dashboard.
- Multi-machine sync health view.
- Automatic snapshot before slicing.
- Conflict merge assistant.
- TUI interface.
- Desktop tray app.
