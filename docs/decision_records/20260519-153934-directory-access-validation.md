# Directory Access Validation On Save

## Context

Willy settings allow users to choose directories with native OS dialogs or edit paths directly. Both paths need the same validation before configuration is saved.

## Decision

Validate directory read/write access in the settings domain layer before persisting paths. The validation lists each directory to confirm read access and creates/removes a temporary probe file to confirm write access.

## Consequences

- Dialog-selected and manually edited paths follow the same save-time rules.
- Configuration is not saved when Willy cannot read or write the selected directories.
- Permission problems are shown as actionable messages that name the failing directory.

