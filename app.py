# Entry point for the whole Prescripts app. Ties every page together under
# one shared look (font, colors, button style) via st.navigation -- adding a
# new page from here on just means adding one entry to
# prescripts_common.PAGES plus dropping in its script file.
import streamlit as st

from prescripts_common import PAGES, SCRIPTS_DIR, inject_button_style, inject_input_style, inject_toast_style

# Black backdrop so the thin, pale-blue linework logo reads against a light
# browser-tab background too -- LOGO_PATH itself stays untouched since every
# page also uses it for its own in-page header, on backgrounds that already
# give it contrast.
FAVICON_PATH = SCRIPTS_DIR.parent / "Images" / "The_Index_Logo_favicon.png"

st.set_page_config(
    page_title="The Prescripts",
    page_icon=str(FAVICON_PATH),
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

st.navigation([home_page, *other_pages]).run()
