# BLS Smart Tables Tool

`BLS Smart Tables Tool` is a production-oriented Streamlit app for ingesting Qualtrics survey exports, cleaning respondent data, auditing survey variables, mapping scale questions, and exporting Excel workbooks.

This V1 release fully implements:

- Data ingestion for `.xlsx` Qualtrics exports
- Metadata row scrubbing
- Blacklisted technical column removal
- Required `cell` column validation and blank-cell respondent removal
- Locked base and cell-letter management
- Survey question audit with heuristic type detection
- Scale mapping and polarity flipping
- Streamlit session-state persistence across reruns
- Multi-sheet placeholder Excel export for downstream workflow testing

The later workflow stages are scaffolded in code so the app remains deployable and extensible without breaking the guided flow.

## Project Structure

```text
.
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

## Deployment

The app is ready for [Streamlit Community Cloud](https://streamlit.io/cloud):

1. Push this repository to GitHub.
2. Create a new Streamlit Community Cloud app pointed at the repository.
3. Set the entrypoint to `app.py`.
4. Streamlit Cloud will install packages from `requirements.txt` automatically.

## Qualtrics Assumptions

- The first row contains variable names.
- The second row contains question labels.
- Additional pre-data rows are treated as metadata when they look like ImportId rows, repeated headers, or Qualtrics metadata.
- A `cell` column is required and is treated as the permanent experimental split.

These assumptions are documented in code comments and were chosen to maximize practical reliability for common Qualtrics exports.
