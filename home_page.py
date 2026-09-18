# Home page: the front door to every other Prescripts page. Deliberately
# light on logic for now -- the search box's real scope is still undecided,
# so it only does simple keyword matching against existing pages. The tile
# grid below it is the primary way to get around for now.
import random

import streamlit as st

from prescripts_common import LOGO_PATH, PAGES, theme_colors, typewriter

# Rotates like a search-portal prompt (Gemini-style) rather than always
# asking the same thing. Picked once per session (below), not re-rolled on
# every rerun, so it doesn't change out from under you mid-interaction.
PROMPTS = [
    "What would you like to look up?",
    "Where should we go today?",
    "What's on your mind?",
    "What can The Prescripts help you find?",
]

TEXT_COLOR, ACCENT_COLOR = theme_colors()

_, logo_col, _ = st.columns([1, 2, 1])
with logo_col:
    st.image(str(LOGO_PATH), width=240)

# Reserved here, in reading order (logo, then question, then the input/tiles
# below), but only actually animated at the very end of the script via the
# typewriter() call there -- so the input box and page tiles render
# immediately instead of waiting on the typing effect to finish.
prompt_placeholder = st.empty()

if "_home_prompt" not in st.session_state:
    st.session_state["_home_prompt"] = random.choice(PROMPTS)

query = st.text_input(
    "Search",
    label_visibility="collapsed",
    placeholder="Type a page name or search term...",
    key="home_query",
)
if st.button("Go") and query:
    query_lower = query.strip().lower()
    matches = [
        page for page in PAGES
        if query_lower in page["title"].lower()
        or any(query_lower in keyword for keyword in page["keywords"])
    ]
    if len(matches) == 1:
        st.switch_page(matches[0]["path"])
    elif len(matches) > 1:
        st.info("More than one page matches that -- try being more specific.")
    else:
        st.info("No page matches that yet.")

st.divider()

tile_cols = st.columns(min(len(PAGES), 3) or 1)
for i, page in enumerate(PAGES):
    with tile_cols[i % len(tile_cols)]:
        with st.container(border=True):
            st.page_link(page["path"], label=page["title"], icon=page["icon"], use_container_width=True)

typewriter(
    st.session_state["_home_prompt"],
    markdown_wrap=":primary[{}]",
    placeholder=prompt_placeholder,
)
