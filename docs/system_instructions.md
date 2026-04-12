# BLS Smart Tables Tool System Instructions

## Product Goal
Build a modular Streamlit application that automates Brand Lift Study table generation from raw survey data through export-ready deliverables.

## Architectural Rules
- Use a page-based architecture rooted under `/app`.
- Keep business logic separate from page layout code.
- Maintain a central `project_config` object in session state.
- Preserve configuration independently from raw respondent data so templates are reusable.

## Required `project_config` Shape
```python
project_config = {
  "project": {},
  "data": {},
  "variables": {},
  "question_types": {},
  "scales": {},
  "nets": {},
  "custom_variables": {},
  "banners": {},
  "filters": {},
  "weights": {},
  "stats": {},
  "topline": {}
}
```

## Page Responsibilities
1. Project Setup
2. Data Intake
3. Survey Question Audit
4. Scale Mapping
5. Net Definitions
6. Custom Variables
7. Banner Configuration
8. Filter Configuration
9. Weighting
10. Statistical Setup
11. Topline Configuration
12. Export

## Coding Practices
- Every function must include plain-English docstrings and comments where necessary.
- Keep page orchestration separate from reusable services.
- Track feature and refactor history in `/docs/changelog.md`.
- Update this file whenever planning logic changes.

## Future-Proofing
- Prepare the architecture for database integration, more file formats, and expanded statistical methods.

