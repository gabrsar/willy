# Native Folder Dialogs For Settings

## Context

Willy's settings UI exposed folder paths as editable text fields and explicitly told users that native folder dialogs were not used. That made configuration harder than needed and invited path typing mistakes.

## Decision

Add Browse buttons that open the system folder chooser for Orca profile, repository, and tracked project folders while keeping direct text editing available.

## Consequences

- Users can select folders through the operating system dialog.
- Existing manual path entry remains available for advanced cases.
- The chooser requires existing folders; Willy's existing save flow still asks whether missing typed paths should be created.

