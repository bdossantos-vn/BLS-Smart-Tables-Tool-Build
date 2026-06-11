# GUIDE

Maintenance note:

- This file is part of the enforced docs-sync set with `PLAN.md` and `STATUS.md`.
- Changes under `app/`, `src/`, `.streamlit/`, or `app.py` should be accompanied by updates to at least one of those docs.

## Purpose

This guide explains how the app interprets the dataset, how rows/columns evolve through the workflow, and what the export pipeline expects.

## Core Data Layers

### 1. Raw upload

Source:

- uploaded Qualtrics-style `.xlsx`

Typical traits:

- includes metadata/header rows
- may include administrative columns
- may contain one or more sheets

In code:

- `raw_df`

### 2. Survey dataframe

Purpose:

- cleaned respondent-level table before comparison-variable row filtering is applied

In code:

- `survey_df`

What it usually contains:

- one row per respondent
- only columns retained after initial cleaning
- original analysis variables used to build metadata and later derived variables

### 3. Working analysis dataframe

Purpose:

- the active dataframe used by later steps and export generation

In code:

- `cleaned_df`

How it differs from `survey_df`:

- applies the selected comparison variable logic
- removes rows where the comparison variable is blank
- applies included question/variable selection

Important:

- many downstream pages use `cleaned_df`, not `raw_df`
- changing included questions/variables or comparison variable changes this active analysis frame

## Row Meaning By Context

### Respondent rows

Most data logic is respondent-level.

That means:

- each row in `survey_df` or `cleaned_df` is one respondent
- banner percentages, topline percentages, and custom variables are all computed from respondent rows

### Metadata rows

Question metadata is stored as a list of dictionaries, not as dataframe respondent rows.

In code:

- `question_metadata`

Each metadata record usually describes:

- `variable`
- `question_label`
- `detected_type`
- answer-choice representations

This layer drives:

- Question Audit
- Scale Mapping
- Nets
- export labeling

### Workbook preview rows

These are not respondent rows.

They are summary rows describing what will be exported, for example:

- sheet name
- table count
- banner/table type

## Question / Variable Meaning In Page 2

### Included questions / variables

These are survey questions or variables that remain in the active working dataset.

Effects:

- they stay available for later workflow steps
- they remain eligible for topline/export if otherwise valid

### Excluded questions / variables

These are survey questions or variables removed during cleaning or kept out of the working dataset.

Effects:

- they are not available for downstream analysis until restored

### Comparison variable

This is the main split variable, often `cell`.

Effects:

- blank comparison rows are removed from `cleaned_df`
- comparison group labels/order drive banner/topline display
- significance logic often keys off this variable

## How Question Types Are Interpreted

### Single-select

Expected shape:

- one stored value per respondent per question

Typical use:

- banners
- filter conditions
- control/test comparison

### Multi-select

Expected shape:

- one cell may contain multiple chosen values
- code assumes delimiter-style storage and normalizes by splitting on `;` and `,`

Important export behavior:

- a single respondent can match multiple selected response options
- for AdHoc crosstabs, row and column handling may differ depending on configuration

### Numeric data

Expected shape:

- numeric-like values in cells

Typical use:

- filter operators such as greater-than / less-than
- possible weighting candidates

### Open-end / ignore

Typical treatment:

- generally not used as banner/crosstab analysis variables
- may be filtered out of analysis-variable catalogs

## Scale Mapping And Nets

### Scale mappings

Purpose:

- define ordered scale points and polarity

Why it matters:

- nets depend on the order
- topline defaults may prefer enabled nets over all raw choices

### Nets

Supported labels:

- `T2B`
- `T3B`
- `B2B`
- `B3B`

Interpretation:

- nets are label-level abstractions over raw answer choices
- the app expands enabled nets back into the underlying raw scale values during analysis

## Custom Variable Shape

Custom variables are materialized as additional respondent-level columns before export logic runs.

### Simple custom variable

Built from:

- one source question
- analyst-defined buckets
- optional fallback bucket

Meaning:

- each respondent is assigned to at most one simple bucket, then optionally to fallback

### Complex custom variable

Built from:

- one or more conditions per bucket
- `ALL` or `ANY` bucket logic
- optional fallback bucket

Meaning:

- each respondent is assigned based on multi-question condition matching

## Banner Shape

Each banner definition can contain:

- `level_1`
- optional `level_2`
- optional `level_3`

Interpretation:

- levels define nested grouping
- the lowest configured level is often the level used for significance comparison logic

Export structure:

- each banner becomes one or more grouped table blocks
- export style can be:
  - one banner per worksheet
  - all banners combined on one worksheet

## AdHoc Crosstab Shape

Each AdHoc table contains:

- `name`
- `row_variable`
- `column_variable`

Interpretation:

- row variable drives the table rows
- column variable drives the table columns
- variables can come from survey questions or saved custom variables

Multi-select caution:

- multi-select variables are not the same as single-select variables
- one respondent may contribute to multiple row/column buckets depending on handling rules

## Filter Shape

Stored as:

- named filter rows
- each filter has branches
- each branch has conditions

Branch meaning:

- branch logic is `ALL` or `ANY`
- each condition uses variable + operator + values

Apply targets:

- `All Tables`
- banner names
- AdHoc crosstab names
- comparison-related targets when present

## Weighting Shape

Weighting exists in config even though the visible page is currently hidden.

Each weight row can include:

- `name`
- `target`
- `source`
- `variables`
- `applies_to`

Interpretation:

- weighting is modeled as configuration metadata passed into later analysis/export stages
- this is not currently the most visible user-facing path in the app

## Statistical Config Shape

There are now two parallel stat configurations:

- `banner_stat_config`
- `adhoc_stat_config`

Each contains fields like:

- `confidence_intervals`
- `alpha`
- `enabled`
- `comparison_scope`
- `include_percentage`
- `include_n_count`
- `include_lift`
- `notation_location`

Important:

- banner stats and AdHoc stats are intentionally separate
- `%`, statistical testing, and N counts are independent export metrics; `%` defaults on for new and older configs

## Topline Shape

Topline config stores:

- `variables`
- `response_selections`
- `note_base_sections`
- `include_lift`
- `include_significance_notes`

Meaning:

- topline rows are not automatically “all responses”
- exact selected response choices should drive what appears
- each variable can also choose whether subgroup notes are based on:
  - `Total Sample`
  - `Total Answering`

## Total Sample vs Total Answering

These are different denominator concepts in export tables.

### Total Sample

Meaning:

- denominator is the total base for the eligible analysis group
- not limited to people who answered that specific question

### Total Answering

Meaning:

- denominator is only respondents who answered that question

Why it matters:

- the same metric row can look different depending on the chosen base
- topline notes and topline metric source should stay aligned to the chosen note base

## Export Package Shape

The export generator builds an intermediate workbook package before writing Excel.

Key structures in `src/tables.py`:

- `SheetTable`
- `WorkbookSheet`
- `ToplineSheet`

Interpretation:

- `SheetTable` is one question table
- `WorkbookSheet` is one worksheet containing one or more `SheetTable`s
- `ToplineSheet` is a flatter summary payload for the `Topline` worksheet

## Project Template Shape

Template export is configuration-only.

Top-level sections include:

- `project`
- `data`
- `variables`
- `question_types`
- `scales`
- `nets`
- `custom_variables`
- `ad_hoc_crosstabs`
- `banners`
- `filters`
- `weights`
- `stats`
- `topline`

Important:

- templates do not carry respondent rows
- templates are meant to restore setup/config, not the uploaded dataset itself

## Practical Interpretation Tips

1. If a variable disappears later in the workflow, first check whether it was excluded on Page 2.
2. If topline/export rows look wrong, check whether the issue is in raw answer choices, enabled nets, or selected topline response options.
3. If a custom variable count seems off, think respondent-level assignment first, especially fallback handling.
4. If banner notes or lift behavior seem odd, inspect the lowest banner level and the comparison-variable structure.
5. If a template loads but later pages still look incomplete, that is often because configuration loaded successfully but no live dataset has been ingested yet.
