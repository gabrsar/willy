# Visible Folder Browse Buttons

## Context

Folder selection buttons existed in the settings UI, but they were placed in secondary action rows and could be missed by users configuring directory paths.

## Decision

Place `Browse...` directly beside each directory path input while keeping text editing and shortcut buttons available.

## Consequences

- Directory selection is visible at the point of data entry.
- Users can still type paths manually.
- Native OS dialogs remain the folder selection mechanism.

