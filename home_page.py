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
FUNCTIONAL_PROMPTS = [
    "What would you like to look up?",
    "Where should we go today?",
    "What's on your mind?",
]

# Partial/fragmentary lines only (by design, not just by trimming) from
# "Children of the City" by Mili feat. Project Moon (album: To Kill a Living
# Book) -- the song the "Prescript" concept itself comes from in Library of
# Ruina canon, where a Prescript is exactly this kind of arbitrary decree
# handed down to a follower. Credited in the footer at the bottom of the
# page (a blanket credit, not a per-line one -- keeps the quote itself
# unadorned when it's shown).
MILI_QUOTES = [
    "Sleep for a total of 800 hours per day",
    "Hero on a plastic horse, riding like it's real",
    "I know now I must be comfortable being who I considered worthless",
    "If we are always running, we can't behold the sceneries",
    "No tears, no regrets, no zero-days at our fault",
    "I am iron; in my blood, it streams roots deep",
]

# General Japanese phrases, not lyric quotes -- no attribution needed.
JAPANESE_PROMPTS = [
    "六根清浄",
    "勝ちたい",
]

PROMPTS = FUNCTIONAL_PROMPTS + MILI_QUOTES + JAPANESE_PROMPTS

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

# Centered via flexbox on stFullScreenFrame -- the wrapper Streamlit adds
# around every image for its hover-to-expand button. That wrapper always
# spans the full column width itself (so the expand button can sit flush
# right), while the fixed-width image inside it just block-flows to the
# left with no auto-centering -- hence the logo reading as "slightly left"
# instead of centered. stElementContainer/stImage aren't the right target:
# stElementContainer's child already fills 100% of it regardless of
# justify-content, and stImage's own box is sized to fit the image exactly
# (nothing left to center within).
st.markdown(
    """
    <style>
    div[data-testid="stFullScreenFrame"] {
        display: flex;
        justify-content: center;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
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

st.divider()
st.caption(
    "Some of the lines above are drawn from \"Children of the City\" by "
    "Mili feat. Project Moon, from the album *To Kill a Living Book* -- "
    "the song the Prescript concept itself comes from."
)
