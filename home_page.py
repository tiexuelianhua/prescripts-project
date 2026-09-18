# Home page: the front door to every other Prescripts page. Deliberately
# light on logic for now -- the search box's real scope is still undecided,
# so it only does simple keyword matching against existing pages. Getting to
# other pages otherwise happens via the sidebar nav that st.navigation
# already renders (see app.py), so there's no second page-link list here.
import random

import streamlit as st

from prescripts_common import LOGO_PATH, PAGES, theme_colors, typewriter

# Rotates like a search-portal prompt (Gemini-style) rather than always
# asking the same thing. Picked once per session (below), not re-rolled on
# every rerun, so it doesn't change out from under you mid-interaction.
# In canon The Prescripts are an authority the page speaks as, issuing
# commands directly to whoever's reading -- so these never name "The
# Prescripts" themselves, the same way a command doesn't refer to its own
# speaker.
PROMPTS = [
    "What would you like to look up?",
    "Where should we go today?",
    "What's on your mind?",
]

TEXT_COLOR, ACCENT_COLOR = theme_colors()

# A blinking "|" in place of the input's placeholder text -- a minimal
# type-here cue instead of a labeled button or instructional placeholder
# text. Scoped to this page only (re-injected fresh each time this script
# runs, gone once navigation swaps in another page).
st.markdown(
    f"""
    <style>
    @keyframes blink-caret {{
        50% {{ opacity: 0; }}
    }}
    div[data-testid="stTextInput"] input::placeholder {{
        color: {TEXT_COLOR};
        opacity: 1;
        animation: blink-caret 1s step-start infinite;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)

_, logo_col, _ = st.columns([1, 2, 1])
with logo_col:
    st.image(str(LOGO_PATH), width=240)

# Reserved here, in reading order (logo, then question, then the input
# below), but only actually animated at the very end of the script via the
# typewriter() call there -- so the input box renders immediately instead of
# waiting on the typing effect to finish.
prompt_placeholder = st.empty()

if "_home_prompt" not in st.session_state:
    st.session_state["_home_prompt"] = random.choice(PROMPTS)

query = st.text_input(
    "Search",
    label_visibility="collapsed",
    placeholder="|",
    key="home_query",
)
# No submit button -- st.text_input already reruns on Enter, so that alone
# is the submit action.
if query:
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

typewriter(
    st.session_state["_home_prompt"],
    markdown_wrap=":primary[{}]",
    placeholder=prompt_placeholder,
)
