# Foundations

Where the project started. None of these files are used by the app.

- `addDay.ps1`: the first script, written by hand. It makes a folder for the day's meal receipts.
- `addDay Script Criteria.pdf`: what a good version of that script had to do.
- `addDay Script Comparison.pdf`: the hand-written script compared with the AI-assisted one (`addDay_cV.ps1`, which the app uses).
- `Overall Project Idea.docx`: the original plan for the project.

## Phase 1

What the first phase covered, and where each part lives now:

| Phase 1 item | Where it is now |
| --- | --- |
| App GUI | `app.py`, opened in its own window by `desktop_app.py` |
| Meal entry method | Budget page, the add form (`prescripts/pages/meal_receipts.py`) |
| Meal recording method | `addDay_cV.ps1` (with `addMonth_cV.ps1` and `addYear_cV.ps1`) makes the day's folder; meals go in its `receipts.csv` |
| Meal total for the day | Budget page, the day's entries |
| Meal total for the month | Budget page, "This month" |
| Prescripts Style established | `prescripts/common.py` (font, colours, page styling) |
| Attribution | Credits on the Home page and in the main README |
