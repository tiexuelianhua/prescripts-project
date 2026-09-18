# Entry point for the whole Prescripts app. Ties every page together under
# one shared look (font, colors, button style) via st.navigation -- adding a
# new page from here on just means adding one entry to
# prescripts_common.PAGES plus dropping in its script file.
import streamlit as st

from prescripts_common import LOGO_PATH, PAGES, inject_button_style

st.set_page_config(page_title="The Prescripts", page_icon=str(LOGO_PATH))
inject_button_style()

home_page = st.Page("home_page.py", title="Home", icon="🏠", default=True)
other_pages = [st.Page(page["path"], title=page["title"], icon=page["icon"]) for page in PAGES]

st.navigation([home_page, *other_pages]).run()
