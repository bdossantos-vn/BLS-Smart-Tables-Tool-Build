# BLS Smart Tables Tool

`BLS Smart Tables Tool` is a Streamlit application for automating Brand Lift Study table production from raw survey data through export-ready tables and toplines.

The codebase has been realigned around a modular, page-based architecture so the product can scale more safely as the research workflow expands.

## Project Structure

```text
.
├── app
│   ├── components
│   ├── models
│   ├── pages
│   ├── services
│   ├── state
│   └── utils
├── docs
├── app.py
├── requirements.txt
├── README.md
└── src
    ├── __init__.py
    ├── cleaning.py
    ├── config.py
    ├── custom_vars.py
    ├── exporter.py
    ├── io.py
    ├── mapping.py
    ├── metadata.py
    ├── state.py
    ├── stats.py
    ├── tables.py
    └── utils.py
```

## Current Refactor Direction

The refactor introduces:

- A modular `app/` package with page-level routing
- A central `project_config` object in session state
- A configuration-only template flow on `Project Setup`
- Dedicated documentation files:
  - `docs/changelog.md`
  - `docs/system_instructions.md`

The existing working page logic is currently preserved in:

- `app/services/legacy_flow.py`

This lets the app keep functioning while we continue moving behavior into cleaner services and models over time.

## Local Run

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Start the app:

```bash
streamlit run app.py
```

4. Open the local Streamlit URL shown in the terminal.

## Template Support

The app now supports a configuration-only template workflow:

- Download current project settings as JSON from `Project Setup`
- Upload that template later to pre-populate future configuration steps
- Templates intentionally exclude respondent-level data

## Deployment

The app is ready for [Streamlit Community Cloud](https://streamlit.io/cloud):

1. Push this repository to GitHub.
2. Create a new Streamlit Community Cloud app pointed at the repository.
3. Set the entrypoint to `app.py`.
4. Streamlit Cloud will install packages from `requirements.txt` automatically.

## Notes

- Existing analyst-tested steps remain preserved while the architecture is being upgraded.
- New product rules and refactor guidance are documented in `docs/system_instructions.md`.
- Feature and refactor history is tracked in `docs/changelog.md`.
