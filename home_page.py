# Home page: the first page, leading to every other Prescripts page. Its box
# takes commands ("go to meal receipts", "what's the weather like") and
# offers a web search for anything that isn't a page -- see
# home_data.route_command. Getting to other pages otherwise happens via the
# sidebar nav that st.navigation already renders (see app.py), so there's no
# second page-link list here.
import random

import streamlit as st

from home_data import add_quote, load_quotes, quote_credit, remove_quote, route_command
from prescripts_common import PAGES, PRIVATE_LOOK, show_logo, theme_colors, typewriter

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

# Partial/fragmentary song lines only (by design, not just by trimming).
# Whichever quote is showing -- one of these or one the user added (see the
# sidebar below, and home_data.py) -- gets credited in the corner note at the
# bottom of the page, just that one, so the note always matches the line on
# screen.
#
# "Children of the City" is the one that matters most: it's the song the
# "Prescript" concept itself comes from in Library of Ruina canon (a Project
# Moon game), where a Prescript is exactly this kind of arbitrary decree
# handed down to a follower -- hence its extra note.
_CHILDREN_OF_THE_CITY_NOTE = (
    "feat. Project Moon, from the album <i>To Kill a Living Book</i> -- "
    "the song the Prescript concept itself comes from"
)
BUILT_IN_QUOTES = [
    {"line": "Sleep for a total of 800 hours per day.", "source": "Children of the City", "by": "Mili",
     "note": _CHILDREN_OF_THE_CITY_NOTE},
    {"line": "Hero on a plastic horse, riding like it's real.", "source": "Hero", "by": "Mili"},
    {"line": "I know now I must be comfortable being who I considered worthless.",
     "source": "Children of the City", "by": "Mili", "note": _CHILDREN_OF_THE_CITY_NOTE},
    {"line": "If we are always running, we can't behold the sceneries.", "source": "TIAN TIAN", "by": "Mili"},
    {"line": "No tears, no regrets, no zero-days at our fault.", "source": "sustain++", "by": "Mili"},
    {"line": "I am iron; in my blood, it streams roots deep.", "source": "Iron Lotus", "by": "Mili"},
]

# General Japanese phrases, not lyric quotes -- no attribution needed.
JAPANESE_PROMPTS = [
    "六根清浄",
    "勝ちたい",
]

user_quotes = load_quotes()
all_quotes = BUILT_IN_QUOTES + user_quotes
PROMPTS = FUNCTIONAL_PROMPTS + [quote["line"] for quote in all_quotes] + JAPANESE_PROMPTS


def _credit_for(prompt: str) -> str:
    # The corner note's first line: where the prompt on screen comes from,
    # or nothing when it isn't a quote.
    quote = next((quote for quote in all_quotes if quote["line"] == prompt), None)
    return quote_credit(quote, escape=quote not in BUILT_IN_QUOTES) if quote else ""


# Adding/removing your own quotes -- in the sidebar, so Home itself stays the
# plain front door. A new quote can come up as the prompt from the next
# visit on (the prompt is picked once per session).
with st.sidebar:
    st.subheader("Your quotes")
    st.caption("Lines that can show up as the prompt here, credited in the corner when they do.")
    with st.form("add_quote", clear_on_submit=True, border=False):
        new_line = st.text_input("Quote")
        new_source = st.text_input("From", placeholder="e.g. a song, book or game")
        new_by = st.text_input("By", placeholder="e.g. the artist or author")
        new_note = st.text_input("Note", placeholder="Optional")
        if st.form_submit_button("Add quote"):
            if new_line.strip():
                add_quote(new_line, new_source, new_by, new_note)
                st.toast("Quote added -- it can come up as the prompt from your next visit.")
                st.rerun()
            else:
                st.warning("Type the quote itself first.")
    for index, quote in enumerate(user_quotes):
        text_column, remove_column = st.columns([5, 1], vertical_alignment="center")
        credit = quote_credit(quote)
        text_column.caption(f"“{quote['line']}”" + (f"  \n{credit}" if credit else ""))
        if remove_column.button("✕", key=f"remove_quote_{index}", help="Remove this quote"):
            remove_quote(index)
            st.rerun()

TEXT_COLOR, ACCENT_COLOR = theme_colors()

# Arriving here (opening the app, or coming back from another page) types
# the prompt in first, then fades in the logo and search box. Reruns while
# staying on Home (e.g. pressing Enter in the box) just show it all at once.
just_arrived = st.session_state.get("_previous_page") != st.session_state.get("_current_page")
# Kept hidden while the prompt types; the footer below starts their fade-in
# once it's done, so the timing follows the typing however long it takes.
# One line each, like the footer's HTML below: a blank line left inside
# that HTML ends it, and Markdown shows the rest as a code block.
_HIDE_UNTIL_TYPED = ".st-key-home_logo, .st-key-home_query { opacity: 0; }" if just_arrived else ""

# A blinking "|" in place of the input's placeholder text -- a minimal
# type-here cue instead of a labeled button or instructional placeholder
# text. Scoped to this page only (re-injected fresh each time this script
# runs, gone once navigation swaps in another page), and to the search box
# alone by its key -- the sidebar's quote fields have ordinary placeholder
# hints that shouldn't blink.
st.markdown(
    f"""
    <style>
    @keyframes blink-caret {{
        50% {{ opacity: 0; }}
    }}
    .st-key-home_query input::placeholder {{
        color: {TEXT_COLOR};
        opacity: 1;
        animation: blink-caret 1s step-start infinite;
    }} {_HIDE_UNTIL_TYPED}
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
with st.container(key="home_logo"):
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
# is the submit action. Commands ("go to meal receipts", "what's the
# weather like") go to their page; anything else is offered as a search.
# The search links open in the user's own browser, not this window.
if query.strip():
    route = route_command(query, PAGES)
    if route["action"] == "page":
        st.switch_page(route["page"]["path"])
    elif route["action"] == "choose":
        st.caption("That could mean more than one page:")
        for page in route["pages"]:
            st.page_link(page["path"], label=page["title"], icon=page["icon"])
    else:
        st.caption("No page for that. Search for it instead?")
        for column, (label, url) in zip(st.columns(len(route["links"])), route["links"]):
            column.link_button(label, url, width="stretch")

if just_arrived:
    typewriter(
        st.session_state["_home_prompt"],
        markdown_wrap=":primary[{}]",
        placeholder=prompt_placeholder,
    )
else:
    prompt_placeholder.markdown(f":primary[{st.session_state['_home_prompt']}]")
# Starts the logo and search box fading in. Sent with the footer below,
# which only reaches the browser once the typing above has finished.
_FADE_IN_AFTER_TYPING = (
    "@keyframes home-fade-in { from { opacity: 0; } to { opacity: 1; } } "
    ".st-key-home_logo, .st-key-home_query { animation: home-fade-in 0.6s ease-out forwards; }"
    if just_arrived
    else ""
)

# The app's one place for attribution (the same list as the README's
# Credits). Collapsed to a single word under the song credit so it adds next
# to nothing to the page; a plain <details> rather than an st.expander, so
# opening it is purely in the browser and doesn't rerun the page. The corner
# note is pinned by its bottom edge, so it opens upwards.
# Only the public look shows the forget-me-not (see PRIVATE_LOOK).
_LOGO_CREDIT = "" if PRIVATE_LOOK else "Forget-me-not logo drawn by a friend of the author."
_CREDITS_HTML = f"""
<details style="margin-top: 0.5rem;">
    <summary style="cursor: pointer;">Credits</summary>
    The Prescripts come from The Index, from Project Moon's games
    (<a href="https://library-of-ruina.fandom.com/wiki/The_Index" target="_blank">Library of Ruina</a>,
    <a href="https://limbuscompany.wiki.gg/wiki/The_Index" target="_blank">Limbus Company</a>).
    {_LOGO_CREDIT}
    Colours and button style:
    <a href="https://prescript.neocities.org/" target="_blank">prescript.neocities.org</a>.
    Font: <a href="https://github.com/quiple/galmuri" target="_blank">Galmuri</a> by quiple (OFL-1.1).
    Weather: <a href="https://www.jma.go.jp/bosai/" target="_blank">JMA</a>.
    Lyrics: <a href="https://lrclib.net" target="_blank">LRCLIB</a>.
    Word lookups: <a href="https://jisho.org" target="_blank">Jisho</a>,
    <a href="https://kanjiapi.dev" target="_blank">kanjiapi.dev</a>.
</details>
"""
# Collapsed onto one line before it's dropped into the footer below: its own
# unindented lines would stop Streamlit dedenting the footer's HTML, and
# Markdown would then show the whole indented footer as a code block.
_CREDITS_HTML = " ".join(_CREDITS_HTML.split())
# The quote's credit (if the prompt is a quote) and the Credits toggle, on
# one line. Not on separate lines: when there's no credit, its empty line
# would end the HTML block, and Markdown would show the rest as code.
_corner_note = " ".join(filter(None, [_credit_for(st.session_state["_home_prompt"]), _CREDITS_HTML]))

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
    }} {_FADE_IN_AFTER_TYPING}
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
        {_corner_note}
    </div>
    """,
    unsafe_allow_html=True,
)
