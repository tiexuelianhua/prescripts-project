# Entry point for the whole Prescripts app. Ties every page together under
# one shared look (font, colors, button style) via st.navigation -- adding a
# new page from here on just means adding one entry to
# prescripts_common.PAGES plus dropping in its script file.
import streamlit as st

from prescripts_common import (
    LOGO_PATH,
    PAGES,
    inject_button_style,
    inject_input_style,
    inject_toast_style,
    render_zoom_controls,
)

st.set_page_config(
    page_title="The Prescripts",
    # Streamlit's own default icon on a fresh clone, which has no logo.
    page_icon=str(LOGO_PATH) if LOGO_PATH.exists() else None,
    # Applies once, on initial load -- which lands on Home (default=True
    # below), the one page with nothing sidebar-worthy on it (Meal Receipts'
    # actual settings live in its own sidebar). Manually expanding it from
    # there is unaffected; this only changes what a fresh session starts on.
    initial_sidebar_state="collapsed",
)
inject_button_style()
inject_input_style()
inject_toast_style()

home_page = st.Page("home_page.py", title="Home", icon="🏠", default=True)
other_pages = [st.Page(page["path"], title=page["title"], icon=page["icon"]) for page in PAGES]

current_page = st.navigation([home_page, *other_pages])
# Which page the previous run was on, so a page can tell "just arrived here"
# from "rerunning while staying here" (e.g. Overview picks a new random
# Japanese word per visit, not per button press). Fragment reruns don't go
# through this script, so they don't count as leaving.
st.session_state["_previous_page"] = st.session_state.get("_current_page")
st.session_state["_current_page"] = current_page.url_path
# Every page but Home gets zoom controls -- Home stays the plain Prescripts
# front door.
if current_page.url_path:
    render_zoom_controls()
current_page.run()
