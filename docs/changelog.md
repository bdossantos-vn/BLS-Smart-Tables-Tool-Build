# Changelog

## 2026-04-12

### Added
- Introduced a page-based `app/` package structure to support future scaling.
- Added a central `project_config` session object to consolidate configuration state.
- Added `Project Setup` and `Topline Configuration` pages to align with the V2 planning spec.
- Added JSON template export/import support for configuration-only project templates.

### Refactored
- Preserved working legacy page logic under `app/services/legacy_flow.py` while routing the UI through page modules.
- Split navigation into a dedicated component module.

### Notes
- This refactor focuses on architecture alignment first, while preserving already working step behavior for analyst testing.

