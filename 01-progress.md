# Willy Progress Tracker

Last updated: 2026-05-13

This file tracks implementation progress. Keep `00-plan.md` as the architecture/design source of truth, and update this file as work is completed, blocked, or re-scoped.

## Status Legend

- `[ ]` Not started
- `[~]` In progress
- `[x]` Done
- `[!]` Blocked or needs decision
- `[?]` Needs verification

## Current Snapshot

- Current phase: Phase 9 - Watch Daemon.
- Current goal: start automatic monitoring now that setup, status, save, metadata, backup, and remote basics exist.
- Next milestone: daemon command with singleton lock, Orca polling, recursive watch loop scaffold, and safe event batching.
- Primary platform: macOS first.
- Later platforms: Windows and Linux after macOS behavior is stable.
- Repository state: Python package skeleton, CLI foundation, config/state/logging helpers, Git wrapper, file classification, backups, locks, metadata extraction, manual save, setup foundation, remote validation, SSH guidance, protection assets, Makefile, Git hooks, and tests exist.

## Immediate Next Actions

1. [x] Create Python package skeleton.
2. [x] Add project metadata and dependency list.
3. [x] Add the initial CLI command surface.
4. [x] Add config, state, and logging path helpers.
5. [x] Add Git wrapper with safe command execution.
6. [x] Add first tests for config paths and Git wrapper behavior.
7. [x] Run the test suite locally.
8. [x] Add Orca file classification and ignore rules.
9. [x] Add backup manager and lock manager.
10. [x] Start safe `willy setup` implementation.
11. [x] Finish interactive setup choices and remote validation.
12. [x] Add SSH key guidance flow.
13. [x] Add AGPL/README protection assets.
14. [ ] Add daemon command and watcher dependencies.
15. [ ] Implement Orca polling watch loop.
16. [ ] Add sync-on-close flow.

## Phase 0 - Planning

- [x] Create architecture plan in `00-plan.md`.
- [x] Capture product goals, UX goals, and safety constraints.
- [x] Capture macOS-first scope and portable-later direction.
- [x] Capture CLI commands and setup flow.
- [x] Capture sync, metadata, conflict, backup, and launchd strategies.
- [x] Create progress tracker in `01-progress.md`.

Exit criteria:

- [x] There is a concrete design doc.
- [x] There is a living progress tracker.
- [x] Implementation can begin without re-deciding the core architecture.

## Phase 1 - Project Skeleton And CLI Foundation

Goal: create a runnable local development project with a minimal but real CLI.

Tasks:

- [x] Create package layout under `src/willy`.
- [x] Add `pyproject.toml`.
- [x] Choose and pin initial runtime dependencies.
- [x] Add CLI entrypoint.
- [x] Implement top-level `willy --help`.
- [x] Implement custom help text that starts with the required TL;DR.
- [x] Add placeholder commands: `setup`, `start`, `stop`, `save`, `history`, `revert`, `help advanced`.
- [x] Add first real `status` command.
- [x] Add clean error formatting for user-facing command failures.
- [x] Add `tests/` structure.
- [x] Add basic smoke test for CLI import and help output.

Acceptance criteria:

- [x] `python -m willy --help` works.
- [x] Installed console script `willy` works in editable install.
- [x] Help output begins with the required TL;DR block.
- [x] Placeholder commands fail safely or print clear "not implemented yet" messages.

Implementation notes:

- Use Python 3.11+.
- Prefer `typer` for CLI.
- Keep command modules small and boring.

## Phase 2 - Config, State, Logging, And Paths

Goal: centralize where Willy reads/writes its own files before touching Orca data.

Tasks:

- [x] Add platform path resolver.
- [x] Define macOS defaults:
  - `~/.willy/config.toml`
  - `~/.willy/state.json`
  - `~/.willy/logs/willy.log`
  - `~/.willy/logs/events.jsonl`
  - `~/.willy/backups`
  - `~/.willy/locks`
- [x] Add config model.
- [x] Add state model.
- [x] Add config load/save.
- [x] Add state load/save.
- [x] Add logging setup.
- [x] Add JSON event logger.
- [x] Add safe directory creation.
- [x] Add tests for default path expansion.
- [x] Add tests for config round-trip.

Acceptance criteria:

- [x] `willy status` can read missing config/state and show useful defaults.
- [x] Running status does not touch Orca profiles.
- [x] Logs are created only when a command actually runs.

## Phase 3 - Git Engine

Goal: wrap Git CLI safely without hiding Git's important failure modes.

Tasks:

- [x] Add Git availability detection.
- [x] Add Git version command.
- [x] Add repo detection.
- [x] Add branch detection.
- [x] Add remote detection.
- [x] Add porcelain status parser.
- [~] Add safe wrappers for:
  - `git init`
  - `git clone`
  - `git add`
  - `git commit`
  - `git status`
  - `git pull --rebase`
  - `git push`
  - `git log`
  - `git restore`
  - `git checkout`
- [x] Add command timeout handling.
- [ ] Add redaction for command logs where needed.
- [x] Add tests using temporary repos.
- [x] Add tests against a local bare repo remote.

Acceptance criteria:

- [x] Git errors are returned as structured application errors.
- [x] Git stdout/stderr is available for debug logs.
- [x] No GitHub API, GitHub CLI, or provider-specific behavior exists.

## Phase 4 - Orca Detection And Filesystem Rules

Goal: safely find Orca and decide what Willy is allowed to track.

Tasks:

- [ ] Add Orca process detector using `psutil`.
- [x] Add fallback process detector for macOS shell commands if needed.
- [x] Add Orca user directory locator.
- [x] Add file classification rules.
- [x] Add ignore rules for temp files, caches, lock files, `.DS_Store`, editor swap files, logs, and Git internals.
- [x] Add allowlist behavior for profile-ish files.
- [x] Decide whether `.info` files are tracked by default.
- [x] Add tests for path classification.
- [x] Add tests using sample Orca-style paths.

Acceptance criteria:

- [~] Setup and revert refuse to run when Orca is open.
- [x] Watcher and Git staging never include `.git`.
- [x] Obvious non-profile junk is ignored.

Open decision:

- [x] v1 tracks JSON only. `.info` sidecars can be read later for metadata but are not versioned by default.

## Phase 5 - Backup Manager And Locks

Goal: guarantee recoverability before any risky operation.

Tasks:

- [x] Add timestamped backup naming.
- [x] Add profile tree backup.
- [ ] Add repo state backup marker.
- [x] Add backup manifest file.
- [x] Add backup listing.
- [x] Add lock manager for daemon singleton.
- [x] Add lock manager for Git operations.
- [x] Add stale lock detection.
- [x] Add tests for backup creation.
- [x] Add tests for lock contention.

Acceptance criteria:

- [x] Setup creates a backup before touching Orca files.
- [ ] Revert creates a backup before restoring.
- [x] A second daemon refuses to start and explains who owns the lock.

## Phase 6 - Setup Flow

Goal: make first-time setup safe for users who do not know Git, SSH, symlinks, or launchd.

Tasks:

- [~] Implement `willy setup`.
- [x] Detect Git installation.
- [x] Print macOS Git install guidance if Git is missing.
- [x] Detect Orca user directory.
- [x] Refuse setup if Orca is running.
- [x] Create backup.
- [x] Ask whether to use existing repo or create new repo.
- [x] Initialize repo in place for new local repo.
- [x] Support existing remote URL.
- [x] Validate remote access using Git/SSH only.
- [x] Detect missing SSH key.
- [x] Offer SSH key generation.
- [x] Print public key and provider-neutral setup instructions.
- [x] Add AGPL-3.0 LICENSE when protection flag is enabled.
- [x] Add README protected section when protection flag is enabled.
- [ ] Offer launchd integration.
- [~] Ensure setup is idempotent.

Acceptance criteria:

- [~] Setup can be run twice without corrupting anything.
- [x] Setup never proceeds while Orca is open.
- [x] New repo path is a valid Git repo.
- [~] Existing repo path is validated before profile data is moved or merged.

## Phase 7 - Metadata Extraction

Goal: make commits readable without making sync depend on perfect metadata.

Tasks:

- [x] Add metadata model.
- [x] Infer profile type from path.
- [x] Parse JSON safely.
- [x] Read fields: `name`, `filament_settings_id`, `printer_settings_id`, `print_settings_id`, `inherits`, `from`.
- [ ] Parse `.info` sidecar when present.
- [x] Infer filament material from filename.
- [x] Infer printer name from machine profile JSON/name/path.
- [x] Add `unknown` fallback for every field.
- [x] Add commit subject formatter.
- [x] Add commit body formatter.
- [x] Add tests for realistic Orca samples.
- [x] Add tests for corrupt JSON.

Acceptance criteria:

- [x] Metadata extraction never blocks a commit.
- [x] Commit messages match the plan format.
- [x] Unknown metadata is explicit, not blank.

## Phase 8 - Manual Save And Status

Goal: provide useful commands before the daemon is complete.

Tasks:

- [x] Implement `willy status`.
- [x] Show Orca running/not running.
- [x] Show watched directory.
- [x] Show repo path.
- [x] Show Git branch.
- [x] Show uncommitted changes.
- [ ] Show remote sync status if a remote exists.
- [x] Show background daemon status.
- [x] Show last commit.
- [x] Implement `willy save "description"`.
- [x] Stage allowed profile files only.
- [x] Commit if meaningful changes exist.
- [x] Print "nothing to save" when clean.
- [x] Add tests for status output with temp repos.
- [~] Add tests for save clean/dirty states.

Acceptance criteria:

- [x] `willy status` is useful before setup and after setup.
- [x] `willy save` never stages ignored files.
- [x] Manual save produces readable commit metadata.

## Phase 9 - Watch Daemon

Goal: automatically commit meaningful changes while Orca runs.

Tasks:

- [ ] Implement daemon command.
- [ ] Poll for Orca process.
- [ ] Enter watch mode when Orca launches.
- [ ] Watch recursively using `watchdog`.
- [ ] Record create/modify/delete/rename events.
- [ ] Debounce noisy writes.
- [ ] Periodically flush long-running batches.
- [ ] Run Git status before committing.
- [ ] Commit meaningful batches.
- [ ] Log watcher batches.
- [ ] Handle watcher errors without corrupting state.
- [ ] Add integration tests around temp directories.

Acceptance criteria:

- [ ] Daemon does nothing while Orca is closed.
- [ ] Daemon starts watching when Orca opens.
- [ ] File changes create commits after debounce.
- [ ] No duplicate daemon instance can run.

## Phase 10 - Sync On Orca Close

Goal: sync safely at the moment Orca exits.

Tasks:

- [ ] Detect Orca exit.
- [ ] Stop watcher.
- [ ] Run final filesystem scan.
- [ ] Commit remaining changes.
- [ ] Create pre-sync safety marker or backup when needed.
- [ ] Run `git pull --rebase`.
- [ ] Run `git push` only when pull/rebase succeeds.
- [ ] Detect rebase conflicts.
- [ ] Abort or pause safely on conflicts.
- [ ] Print recovery instructions.
- [ ] Log sync result.
- [ ] Update state with last sync summary.
- [ ] Add local bare remote integration tests.
- [ ] Add conflict simulation tests.

Acceptance criteria:

- [ ] Sync never overwrites silently.
- [ ] Local commits remain intact if remote is unavailable.
- [ ] Conflict path creates recovery guidance and preserves data.

## Phase 11 - History And Revert

Goal: make Git history useful without requiring Git knowledge.

Tasks:

- [ ] Implement `willy history`.
- [ ] Show recent commits.
- [ ] Group by printer.
- [ ] Group by filament.
- [ ] Group by profile type.
- [ ] Add filters: `--printer`, `--filament`, `--profile-type`, `--since`.
- [ ] Implement `willy revert`.
- [ ] Show backups.
- [ ] Show recent commits.
- [ ] Explain consequences.
- [ ] Preview changed paths.
- [ ] Create backup before restore.
- [ ] Restore selected commit or path.
- [ ] Add tests for history parsing.
- [ ] Add tests for revert preview.
- [ ] Add tests for revert backup.

Acceptance criteria:

- [ ] Revert requires explicit confirmation for destructive changes.
- [ ] Revert always creates a backup first.
- [ ] History is readable without Git terminology.

## Phase 12 - launchd Integration

Goal: make automatic sync easy to keep running on macOS.

Tasks:

- [ ] Generate LaunchAgent plist.
- [ ] Install plist at `~/Library/LaunchAgents/com.willy.sync.plist`.
- [ ] Implement `willy start`.
- [ ] Implement `willy stop`.
- [ ] Detect loaded/running agent state.
- [ ] Show daemon state in `willy status`.
- [ ] Log launchd install/start/stop actions.
- [ ] Add manual macOS verification checklist.

Acceptance criteria:

- [ ] `willy start` starts background syncing.
- [ ] `willy stop` stops background syncing cleanly.
- [ ] Re-running start/stop is idempotent.

## Phase 13 - Hardening And Release Prep

Goal: turn the prototype into something safe to use for real profiles.

Tasks:

- [ ] Review all commands for backup coverage.
- [ ] Review all commands for lock coverage.
- [ ] Add dry-run behavior where command signatures expose it.
- [ ] Add user-facing error guide.
- [ ] Add README.
- [ ] Add install instructions.
- [ ] Add troubleshooting docs.
- [ ] Add sample config.
- [ ] Run full test suite.
- [ ] Run manual test against a copied Orca profile directory.
- [ ] Run manual test against a local bare Git remote.
- [ ] Run manual launchd test.
- [ ] Package for local install.

Acceptance criteria:

- [ ] No known path can delete or overwrite profile files without backup.
- [ ] All main commands have tests or manual verification notes.
- [ ] README explains setup without assuming Git knowledge.

## Cross-Platform Backlog

Do not start until macOS flow is stable.

- [ ] Add Windows Orca profile path discovery.
- [ ] Add Linux Orca profile path discovery.
- [ ] Replace launchd integration with platform service abstraction.
- [ ] Add Windows service or scheduled task support.
- [ ] Add systemd user service support.
- [ ] Validate file watcher behavior on Windows.
- [ ] Validate file watcher behavior on Linux.
- [ ] Add platform-specific docs.

## Open Decisions

- [x] Track JSON only, or JSON plus `.info` sidecars? Chosen: JSON only for v1.
- [x] Should `hints.cereal` be tracked by default? Chosen: no for v1.
- [!] Should `willy setup` allow symlink mode at all in v1, or leave it as future advanced mode?
- [!] Should automatic commits include timestamp in the subject, or rely on Git commit timestamps?
- [!] Should the initial implementation include dry-run behavior everywhere, or only where already exposed in command signatures?

## Decision Log

- [x] Python is the implementation language.
- [x] macOS is the first target.
- [x] Windows and Linux are future targets.
- [x] Git operations use standard Git CLI only.
- [x] No GitHub API dependency.
- [x] No GitHub CLI dependency.
- [x] Default setup prefers in-place Git repo inside Orca `user`.
- [x] Setup refuses to run while OrcaSlicer is open.
- [x] Safety favors backups and explicit recovery over invisible conflict handling.
- [x] v1 stages JSON files only; `.info` and `hints.cereal` are not tracked by default.
- [x] Setup validates remotes using Git CLI only.
- [x] Setup protection uses AGPL-3.0 only, not a custom anti-company license.

## Verification Log

Add dated entries as checks are run.

```text
YYYY-MM-DD HH:mm | command/check | result | notes
2026-05-13 17:18 | .venv/bin/python -m pytest | pass | 11 tests passed
2026-05-13 17:18 | .venv/bin/willy --help | pass | output starts with required TL;DR
2026-05-13 17:18 | .venv/bin/willy status | pass | detected local Orca running; no Git repo in Orca user dir
2026-05-13 17:25 | .venv/bin/python -m pytest | pass | 24 tests passed
2026-05-13 17:25 | .venv/bin/python -m willy --help | pass | output starts with required TL;DR
2026-05-13 17:25 | .venv/bin/willy status | pass | status command still works after save/setup additions
2026-05-13 17:32 | make install | pass | refreshed editable install and installed Ruff
2026-05-13 17:32 | make lint | pass | Ruff formatted/fixed project files
2026-05-13 17:32 | make test | pass | 24 tests passed
2026-05-13 17:33 | make setup | pass | initialized Git repo and installed pre-commit/pre-push hooks
2026-05-13 17:45 | make lint | pass | setup/SSH/protection additions lint clean
2026-05-13 17:45 | make test | pass | 31 tests passed
2026-05-13 18:00 | make lint && make test | pass | 33 tests passed; bad remote no longer prints traceback
2026-05-13 18:00 | .venv/bin/willy setup --remote git@github.com:gabrsar/orca-configs.git | pass | fails cleanly before backup/init when remote is inaccessible
```

## Change Log

- 2026-05-13: Created tracker from `00-plan.md`.
- 2026-05-13: Added Python project skeleton, CLI, config/state/logging helpers, Git wrapper, tests, and `.gitignore`.
- 2026-05-13: Added JSON-only file classification, backup manager, lock manager, setup foundation, metadata extraction, and manual save.
- 2026-05-13: Added Makefile, Ruff dev dependency, local setup target, and Git hooks.
- 2026-05-13: Added setup mode selection, remote validation, SSH key guidance, and AGPL/README protection assets.
- 2026-05-13: Fixed CLI Git error boundary and moved remote validation before setup mutations.
