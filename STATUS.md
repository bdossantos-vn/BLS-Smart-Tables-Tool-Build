# STATUS

Maintenance note:

- This file is part of the enforced docs-sync set with `PLAN.md` and `GUIDE.md`.
- Changes under `app/`, `src/`, `.streamlit/`, or `app.py` should be accompanied by updates to at least one of those docs.

## Snapshot

This status reflects the repository state as of 2026-05-01.

## Overall State

- The app is functionally broad and fairly feature-rich.
- The main workflow is present from setup through Excel export.
- Several newer features are implemented but still need deeper end-to-end regression testing.
- Some legacy code paths still exist behind the current modular app shell.
- Template import/export exists in code, but should be treated as only partially verified until round-trip testing is completed.

## Status Rubric

This file uses the following status meanings:

- `Working`
  - implemented in code
  - wired into the current visible app flow
  - no known immediate blocker in the current build

- `Working, lightly verified`
  - implemented and visible
  - appears operational from code review and/or limited validation
  - not deeply regression-tested end to end

- `Working, needs regression verification`
  - implemented and visible
  - recently changed, historically fragile, or broad enough that follow-up testing is still needed

- `Implemented in legacy code, not exposed`
  - present in code/config/state handling
  - not currently exposed as part of the main visible workflow

- `Partially verified`
  - implemented, but only some expected behavior has been confirmed
  - remaining branches, edge cases, or round-trip paths still need validation

- `Untested`
  - present in code, but not yet validated enough to claim working behavior confidently

Status is determined from a mix of:

- whether the feature is wired into the current page registry and navigation
- whether the behavior exists only in legacy paths or hidden code paths
- whether the feature is actively passed through generation/export layers
- whether it has been recently changed
- how much direct validation or regression checking has been done

## Visible Workflow Status

### 1. Project Setup

Status: `Working, lightly verified`

Implemented:

- start from scratch
- upload configuration template (`.json`)

Known caveats:

- template upload depends on config compatibility, not respondent-data restoration
- end-to-end template round-trip should still be treated as needing explicit verification

### 2. Data Intake

Status: `Working, recently changed, needs regression verification`

Implemented:

- upload Qualtrics Excel file
- choose a sheet when multiple sheets exist
- process and clean the dataset
- choose/apply comparison variable
- comparison label editing
- comparison group order controls
- included/excluded column controls
- change log

Recent risk area:

- Page 2 grid styling and control rendering were recently refactored several times
- included/excluded selectors are now back on native `st.data_editor` to match Page 3 more closely
- visual behavior should be considered recently stabilized, but still worth user verification

### 3. Survey Question Audit

Status: `Working`

Implemented:

- metadata table via `st.data_editor`
- review/edit detected question type
- edit answer-choice labels
- change log

### 4. Scale Mapping

Status: `Working, hardened recently`

Implemented:

- scale question detection
- ordered scale points
- polarity selection
- save flow and change log

Recent stability work:

- standalone page implementation
- repair of persisted stale scale orders
- protection against label-order collisions such as `Like it` / `Dislike it`

### 5. Net Definitions

Status: `Working`

Implemented:

- per-scale net toggles
- bulk net toggles
- T2B / T3B / B2B / B3B scaffolding

### 6. Custom Variables

Status: `Working, medium complexity, should be regression-tested`

Implemented:

- simple custom variables
- complex custom variables
- unmatched-response fallback handling
- preview counts
- saved custom variable summary
- edit/delete custom variables

Risk areas:

- multi-condition logic
- fallback categories
- interactions with filters and export rows

### 7. Banner Configuration

Status: `Working`

Implemented:

- up to 3 nested levels
- named banners
- include total column
- export style:
  - `1 banner per sheet`
  - `All banners in single sheet`

### 8. Custom AdHoc Crosstabs

Status: `Working, recently expanded, should be regression-tested`

Implemented:

- row variable selection
- column variable selection
- survey questions + custom variables in catalog
- multiple AdHoc table definitions on one page
- exports grouped on one sheet

Recent risk areas:

- multi-select row behavior
- multi-select column selected/not-selected behavior
- response-selection behavior when tied to configured question selections

### 9. Filter Configuration

Status: `Working`

Implemented:

- multiple named filters
- branch logic (`ALL` / `ANY`)
- multi-condition filters
- apply targets:
  - all tables
  - banners
  - AdHoc crosstabs
  - comparison variable target when relevant

### 10. Statistical Setup

Status: `Working`

Implemented:

- separate banner settings
- separate AdHoc settings
- primary and optional secondary CI
- lift toggle
- N count toggle
- statistical comparison mode, including `None`
- notation location:
  - appended to metric
  - below metric

Notes:

- the old “independent two-sample z test scaffold” control is effectively hidden from the visible UX

### 11. Topline Configuration

Status: `Working, high-change area, needs continued regression testing`

Implemented:

- include/exclude topline variables
- default response choices
- exact selected response choices
- bulk note-base actions
- per-variable note base (`Total Sample` / `Total Answering`)
- topline lift toggle
- topline significance-notes toggle
- change log

Recent risk areas:

- exact response carryover into export
- note-base alignment with actual topline metric source
- subgroup note generation rules

### 12. Export

Status: `Working, broadest regression surface`

Implemented:

- readiness summary
- workbook package generation
- workbook preview
- Excel workbook download
- project template download

Workbook/export features currently present in code:

- visible version/layout stamp
- topline sheet
- banner sheets or combined banner sheet
- AdHoc crosstab sheet
- total sample vs total answering sections
- comparison label propagation
- lifts
- significance notation location
- footnotes for stats / filters / weighting context

## Hidden / Less-Visible Features

### Hidden Weighting Configuration

Status: `Implemented in legacy code, not exposed in current sidebar`

What exists:

- weighting row builder in legacy flow
- weighting config defaults and validation
- weighting section in config/template model
- weighting passed into workbook generation

What is missing from current visible app:

- no active sidebar route/page for weighting in the current registry

Interpretation:

- weighting is a code-level feature with partial architecture support
- it should be treated as hidden and not fully productized in the current visible flow

### Legacy step redirects

Status: `Working but transitional`

- the app still contains label redirects and legacy page implementations
- this supports compatibility, but also means behavior can live in two architectural styles at once

## Template Upload / Download Status

### Download template

Status: `Implemented, likely working, not fully regression-tested`

- current project config is serialized to JSON
- intended to exclude respondent data

### Upload template

Status: `Implemented, partially verified, needs explicit round-trip testing`

- loads configuration sections into session state
- does not restore respondent rows
- depends on current config structure remaining compatible

Known caution:

- if a page expects live cleaned data but only a template has been loaded, some parts of the workflow may remain unavailable until data is ingested again

## Testing Status

Observed in repo:

- active code compiles cleanly after recent edits
- no strong evidence of a broad automated regression suite covering workflow behavior end to end

Practical meaning:

- “implemented” does not always mean “fully tested”
- recent UI/theme/grid changes especially should be treated as requiring manual validation

## Unfinished Or Untested Areas To Watch

- template upload/download round-trip
- hidden weighting flow
- Page 2 grid visual consistency after recent renderer/theme changes
- AdHoc multi-select edge cases
- complex significance note logic across all banner structures
- full workbook regression across:
  - one banner per sheet
  - all banners in one sheet
  - binary and non-binary lift cases
  - note-base differences
  - notation location differences
