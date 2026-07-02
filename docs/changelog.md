# Changelog

## 2026-07-02

### Added
- Added Snowflake survey intake, including Snowpark connection helpers and survey-response query support.
- Added long-format Snowflake cleaning that pivots question rows into respondent-level analysis data.
- Added hidden respondent identity handling so unique respondent counts survive long-format ingestion.
- Added shared multiselect safeguards for stale, blank, or invalid Streamlit selections.

### Changed
- Extended project settings snapshots so saved configuration can be restored against uploaded or Snowflake data.
- Updated topline configuration/export behavior for exact selected responses, note-base handling, lift columns, and significance notes.
- Updated export caching/progress behavior to avoid storing respondent-level data in signatures.
- Treated generated workbook exports as local artifacts rather than committed source files.

### Verified
- Full local regression suite passes under the app environment: 74 tests.

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
