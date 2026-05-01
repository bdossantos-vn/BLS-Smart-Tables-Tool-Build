# PLAN

Maintenance note:

- This file is part of the enforced docs-sync set with `STATUS.md` and `GUIDE.md`.
- Changes under `app/`, `src/`, `.streamlit/`, or `app.py` should be accompanied by updates to at least one of those docs.

## Purpose

This repository is a Streamlit-based table-building tool for survey analysis. Its job is to:

- ingest a Qualtrics-style Excel export
- clean the respondent data into an analysis-ready dataframe
- let analysts define metadata, scales, nets, custom variables, banners, filters, statistical settings, and topline behavior
- generate a branded Excel workbook with topline, banner tables, and AdHoc crosstabs
- export and re-import a configuration-only project template

## Current Architecture

### App shell

- `app.py`
  - sets the Streamlit page shell
  - initializes state
  - applies the shared theme
  - renders sidebar navigation
  - routes to page modules

### Shared UI

- `app/components/navigation.py`
  - visible step registry
  - current page selection
  - `Back` / `Next`
  - `Start New Project`
- `app/components/theme.py`
  - branding CSS
  - sidebar styling
  - button treatment
  - main-surface overrides
- `app/components/branding.py`
  - brand header and sidebar brand block

### State + template persistence

- `app/state/manager.py`
  - bootstraps app-level defaults
  - syncs session state into one `project_config`
  - exports configuration-only templates
  - loads configuration-only templates
- `app/models/project_config.py`
  - canonical template/config skeleton

### Core analysis logic

- `src/cleaning.py`
  - Excel ingestion and cleaning
- `src/metadata.py`
  - question metadata and answer choice handling
- `src/mapping.py`
  - scale mapping and polarity
- `src/nets.py`
  - T2B / T3B / B2B / B3B definitions
- `src/custom_vars.py`
  - simple and complex custom variables
- `src/config.py`
  - builders/defaults for banners, filters, weights, stats, AdHoc, validation
- `src/stats.py`
  - statistical setup normalization and validation
- `src/tables.py`
  - workbook package generation
  - topline rows
  - banner tables
  - AdHoc crosstabs
  - notes / lift / significance helpers
- `src/exporter.py`
  - branded Excel workbook output

### Page layer

Visible current pages:

1. `Project Setup`
2. `Data Intake`
3. `Survey Question Audit`
4. `Scale Mapping`
5. `Net Definitions`
6. `Custom Variables`
7. `Banner Configuration`
8. `Custom AdHoc Crosstabs`
9. `Filter Configuration`
10. `Statistical Setup`
11. `Topline Configuration`
12. `Export`

Legacy-backed pages still rendered through `app/services/legacy_flow.py`:

- Data Intake
- Survey Question Audit
- Custom Variables
- Banner Configuration
- Filter Configuration
- hidden Weighting page implementation

Standalone page implementations:

- Project Setup
- Scale Mapping
- Net Definitions
- AdHoc Crosstabs
- Statistical Setup
- Topline Configuration
- Export

## Feature Roadmap

### Track 1: Stabilize what exists

1. Lock down Page 2 and Page 3 grid behavior
   - keep Page 2 visually aligned with Page 3
   - prevent white-on-white regressions in `st.data_editor`
   - confirm hover/button styling inside expanders

2. Harden template import/export
   - verify end-to-end import from empty session
   - verify export after full project setup
   - confirm all current config sections survive round-trip
   - define expected behavior for fields that should not restore data rows

3. Regression-test workbook generation
   - topline selected responses
   - note base alignment
   - banner export style: one sheet vs combined sheet
   - AdHoc multi-select handling
   - footnotes, lifts, notation placement
   - comparison labels across all sheets

4. Verify hidden code paths
   - weighting configuration logic
   - older legacy step numbering / redirects
   - compatibility between legacy state and refactored page registry

### Track 2: Reduce architecture risk

1. Move more legacy pages out of `legacy_flow.py`
   - Data Intake
   - Survey Question Audit
   - Custom Variables
   - Banner Configuration
   - Filter Configuration

2. Centralize page-specific state models
   - avoid mixing transient widget state with canonical config state
   - define explicit “saved config” vs “editor/session draft” layers

3. Normalize workbook package contracts
   - document all sheet payload structures
   - reduce exporter-specific assumptions
   - make notes/lifts/footnotes easier to test in isolation

4. Add a real validation layer for project templates
   - schema checks
   - version compatibility checks
   - migration path for old templates

### Track 3: Improve analyst experience

1. Better inline previews
   - preview banner table structure before export
   - preview AdHoc output before export
   - preview filters against counts more explicitly

2. Safer configuration UX
   - save-state summaries per page
   - warnings for contradictory config
   - clearer untreated / ignored variables

3. Better workbook transparency
   - version stamp already exists
   - expand export notes/metadata summary
   - possibly add a config summary sheet

### Track 4: Testing + maintainability

1. Add automated tests around:
   - cleaning
   - metadata and scale ordering
   - nets
   - custom variable evaluation
   - filter application
   - topline response selection
   - workbook package generation

2. Add fixture datasets and template fixtures

3. Add smoke tests for:
   - fresh project flow
   - template import
   - workbook export

## Feature Inventory To Keep In Scope

The roadmap should continue to account for all of these, not just the visible ones:

- project template upload
- project template download
- intake comparison variable logic
- comparison group relabeling and ordering
- included/excluded column controls
- question audit answer choice edits
- scale mapping and polarity
- net definitions
- simple custom variables
- complex custom variables
- banner configuration
- banner export style
- AdHoc crosstabs
- global filters with branches and conditions
- hidden weighting configuration
- separate banner vs AdHoc statistical settings
- topline response selection
- topline note base selection
- workbook preview and final Excel export
