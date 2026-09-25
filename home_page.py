# Home page: the front door to every other Prescripts page. Deliberately
# light on logic for now -- the search box's real scope is still undecided,
# so it only does simple keyword matching against existing pages. Getting to
# other pages otherwise happens via the sidebar nav that st.navigation
# already renders (see app.py), so there's no second page-link list here.
import random

import streamlit as st

from prescripts_common import PAGES, show_logo, theme_colors, typewriter

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

# Partial/fragmentary lines only (by design, not just by trimming), each
# from a different Mili song -- not all from "Children of the City" despite
# that being the one that matters most: it's the song the "Prescript"
# concept itself comes from in Library of Ruina canon (a Project Moon game),
# where a Prescript is exactly this kind of arbitrary decree handed down to
# a follower. Every song is credited in the footer at the bottom of the page
# (a blanket credit, not inline per-line -- keeps the quote itself unadorned
# when it's shown), built from the song names below so it can't drift out of
# sync with this list.
MILI_QUOTES = [
    ("Sleep for a total of 800 hours per day.", "Children of the City"),
    ("Hero on a plastic horse, riding like it's real.", "Hero"),
    (
        "I know now I must be comfortable being who I considered worthless.",
        "Children of the City",
    ),
    ("If we are always running, we can't behold the sceneries.", "TIAN TIAN"),
    ("No tears, no regrets, no zero-days at our fault.", "sustain++"),
    ("I am iron; in my blood, it streams roots deep.", "Iron Lotus"),
]

# General Japanese phrases, not lyric quotes -- no attribution needed.
JAPANESE_PROMPTS = [
    "六根清浄",
    "勝ちたい",
]

PROMPTS = FUNCTIONAL_PROMPTS + [text for text, _ in MILI_QUOTES] + JAPANESE_PROMPTS


def _oxford_quoted_list(items: list[str]) -> str:
    quoted = [f'"{item}"' for item in items]
    if len(quoted) == 1:
        return quoted[0]
    return ", ".join(quoted[:-1]) + ", and " + quoted[-1]


# Order of first appearance in MILI_QUOTES, de-duplicated -- dict.fromkeys
# preserves insertion order and drops repeats (Children of the City appears
# twice above).
_MILI_SONGS = list(dict.fromkeys(song for _, song in MILI_QUOTES))

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
show_logo(width=240)

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

# Pinned to the corner via CSS rather than st.caption's normal inline flow,
# so it reads as a page-level footer note instead of sitting right under the
# search box. Fades in on load (matches the typewriter's gradual-reveal feel
# elsewhere on this page, rather than popping in suddenly); the animation's
# end opacity matches the div's base opacity, so it settles there once the
# animation finishes rather than needing animation-fill-mode.
st.markdown(
    f"""
    <style>
    @keyframes footer-fade-in {{
        from {{ opacity: 0; }}
        to {{ opacity: 0.6; }}
    }}
    </style>
    <div style="
        position: fixed;
        bottom: 12px;
        right: 16px;
        max-width: 320px;
        font-size: 0.8rem;
        color: {TEXT_COLOR};
        opacity: 0.6;
        animation: footer-fade-in 1.5s ease-in;
        text-align: right;
        z-index: 100;
    ">
        Some of the lines above are drawn from Mili songs -- {_oxford_quoted_list(_MILI_SONGS)}.
        "Children of the City" (feat. Project Moon, from the album
        <i>To Kill a Living Book</i>) is the song the Prescript concept
        itself comes from.
    </div>
    """,
    unsafe_allow_html=True,
)
