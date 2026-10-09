# Japanese page: flashcards for vocab and kanji, reviewed on a spaced-
# repetition (SRS) schedule -- either revealed and self-graded, or typed and
# checked (realkana-style) -- plus a lookup of the whole deck. Cards new to
# the user start in Learn, studied at their own pace before reviews. New
# cards can be filled in from Jisho / kanjiapi.dev. Grammar points are
# reviewed on the deck's own words (data/japanese/grammar.py). The public
# version also has a kana drill for beginners (data/japanese/kana.py). All data/
# scheduling lives in data/japanese/ (no UI there), so the Overview tile
# can read it too.
import base64
import html
import random
import urllib.error
import uuid

import pandas as pd
import streamlit as st

from prescripts.common import PRIVATE_LOOK, inject_body_fade_in, render_page_title, show_logo, theme_colors, typewriter
from prescripts.data.japanese.answers import (
    STEP_LABELS,
    answer_steps,
    check_step,
    display_readings,
    has_distinct_reading,
)
from prescripts.data.japanese.deck import (
    GRADE_LABELS,
    GRADES,
    KIND_LABELS,
    KINDS,
    PRACTICE_SETS,
    add_card,
    delete_cards,
    due_cards,
    find_duplicate,
    format_interval,
    in_practice_set,
    learning_cards,
    load_deck,
    load_drawing,
    next_schedule,
    regrade,
    review_card,
    save_deck,
    save_drawing,
    search_cards,
    set_learning,
    today_jst,
    update_card,
)
from prescripts.data.japanese.grammar import (
    STARTER_POINTS,
    WORD_TYPES,
    add_grammar_point,
    add_starter_points,
    conjugate,
    fitting_words,
    pick_word,
    read_more,
    typed_prompt,
)
from prescripts.data.japanese.kana import KANA_SETS, SCRIPTS, check_kana, kana_pool, kana_settings, next_kana
from prescripts.data.japanese.learning import RULES_OF_THUMB, kanji_in, reading_in_word, words_using
from prescripts.data.japanese.lookups import jisho_lookup, kanji_lookup, part_of_speech_for
from prescripts.data.japanese.spelling import check_new_card
from prescripts.data.japanese.stations import add_station_cards, new_stations
from prescripts.drawing_widget import drawing_box

TEXT_COLOR, ACCENT_COLOR = theme_colors()
PAGE_TITLE = "Japanese"
# Choices for the deck filters (review and lookup): both kinds, or just one.
DECK_FILTERS = {"All": KINDS, "Vocab": ["vocab"], "Kanji": ["kanji"], "Grammar": ["grammar"]}

is_first_load = "_japanese_title_played" not in st.session_state
inject_body_fade_in("main_body")

header_logo, header_title = st.columns([1, 4], vertical_alignment="center")
with header_logo:
    show_logo(width=120)
with header_title:
    render_page_title(PAGE_TITLE, is_first_load)

if is_first_load:
    st.session_state["_japanese_title_played"] = True

# The flashcard: accent-outlined like the Overview tiles, with the front
# (the kanji / written word) large enough to read stroke detail. The front
# alone is in Windows' own Japanese font rather than the app's pixel font:
# Galmuri draws kanji on a small bitmap grid, which drops strokes from dense
# ones (checked: 鬱 came out unrecognisable) -- and the strokes are the
# point of a kanji card. Reading and meaning stay in the pixel font.
st.markdown(
    f"""
    <style>
    .flashcard {{
        border: 1px solid {ACCENT_COLOR};
        padding: 2rem 1rem 1.5rem;
        text-align: center;
        margin-bottom: 1rem;
    }}
    .flashcard-front {{
        font-family: "Yu Gothic UI", "Yu Gothic", "Meiryo", sans-serif;
        font-size: 4rem;
        line-height: 1.2;
    }}
    .flashcard-kind {{
        opacity: 0.6;
        font-size: 0.85em;
        margin-bottom: 0.5rem;
    }}
    .flashcard-reading {{
        font-size: 1.6rem;
        margin-top: 1rem;
        color: {ACCENT_COLOR};
    }}
    .flashcard-meaning {{
        font-size: 1.3rem;
        margin-top: 0.5rem;
    }}
    .flashcard-pos {{
        opacity: 0.6;
        font-size: 0.85em;
        margin-top: 0.4rem;
    }}
    .flashcard-note {{
        font-style: italic;
        opacity: 0.8;
        margin-top: 0.8rem;
    }}
    .flashcard-drawing {{
        position: relative;
        width: 160px;
        height: 160px;
        margin: 0.8rem auto 0;
        border: 1px solid {ACCENT_COLOR}55;
    }}
    .flashcard-drawing span {{
        position: absolute;
        inset: 0;
        display: flex;
        align-items: center;
        justify-content: center;
        font-family: "Yu Gothic UI", "Yu Gothic", "Meiryo", sans-serif;
        opacity: 0.18;
        line-height: 1;
    }}
    .flashcard-drawing img {{
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
    }}
    .flashcard-kanji-reading {{
        margin-top: 0.4rem;
    }}
    /* The Deck buttons already scroll sideways when they don't fit (zoomed
       in, say), but Streamlit hides the scrollbar, so nothing shows there's
       more. A thin one appears then. */
    .st-key-japanese_lookup_filter [data-testid="stButtonGroup"] > div,
    .st-key-japanese_review_filter [data-testid="stButtonGroup"] > div {{
        scrollbar-width: thin;
        scrollbar-color: {ACCENT_COLOR} transparent;
    }}
    /* Kana set names and the kana drill's last answer: the pixel font loses
       the small marks that tell ば, ぱ and は apart. */
    .st-key-japanese_kana_sets button *, .kana-plain {{
        font-family: "Yu Gothic UI", "Yu Gothic", "Meiryo", sans-serif;
    }}
    .flashcard-kanji-reading span {{
        opacity: 0.6;
        font-size: 0.85em;
        margin-right: 0.4rem;
    }}
    </style>
    """,
    unsafe_allow_html=True,
)


def kanji_breakdown(deck: dict, card: dict) -> str:
    # A word's kanji (the ones in the deck) and the reading each uses in it:
    # "学 probably on ガク · 校 on コウ". Empty for kanji cards, kana words
    # and words whose kanji aren't in the deck.
    if card["kind"] != "vocab":
        return ""
    return " · ".join(
        f"{kanji['front']} {reading_label(reading_in_word(kanji, card['front'], card['reading'] or card['front']))}"
        for kanji in kanji_in(deck, card)
    )


def render_grammar_card(point: dict, word: dict | None, show_back: bool) -> None:
    # The front is the point on a word from the deck (静かじゃなかった), to
    # read and understand; the back reads it out and splits it into the word
    # and the point. With no word that fits, just the point itself.
    front = conjugate(point, word)["front"] if word else f"～{point['front']}"
    back = ""
    if show_back:
        if word:
            back += f'<div class="flashcard-reading">{html.escape(conjugate(point, word)["reading"])}</div>'
        back += (f'<div class="flashcard-meaning"><span lang="ja">～{html.escape(point["front"])}</span> '
                 f'{html.escape(point["meaning"])}</div>')
        if word:
            word_reading = f" ({word['reading']})" if has_distinct_reading(word) else ""
            back += (f'<div class="flashcard-pos"><span lang="ja">{html.escape(word["front"] + word_reading)}</span> '
                     f'{html.escape(word["meaning"])}</div>')
        if point.get("note"):
            back += f'<div class="flashcard-note">{html.escape(point["note"])}</div>'
        link = read_more(point)
        if link:
            back += (f'<div class="flashcard-pos">Read more: <a href="{link[1]}" target="_blank">'
                     f'{html.escape(link[0])}</a></div>')
    st.markdown(
        f'<div class="flashcard"><div class="flashcard-kind">Grammar</div>'
        f'<div class="flashcard-front" lang="ja">{html.escape(front)}</div>{back}</div>',
        unsafe_allow_html=True,
    )
    if not word:
        st.caption(f"None of your words fit it yet. It goes on {attaches_label(point).lower()}.")


def render_grammar_prompt(asked: dict) -> None:
    # Typed answers: the word and what the point means, to put together
    # (静か quiet + "wasn't (casual)" -> 静かじゃなかった).
    word = asked["word"]
    word_reading = f"{word['reading']} · " if has_distinct_reading(word) else ""
    st.markdown(
        f'<div class="flashcard"><div class="flashcard-kind">Grammar</div>'
        f'<div class="flashcard-front" lang="ja">{html.escape(word["front"])}</div>'
        f'<div class="flashcard-pos"><span lang="ja">{html.escape(word_reading)}</span>{html.escape(word["meaning"])}</div>'
        f'<div class="flashcard-meaning">+ {html.escape(asked["meaning"])}</div></div>',
        unsafe_allow_html=True,
    )


def attaches_label(point: dict) -> str:
    # ["noun", "na-adjective"] -> "Nouns, Na-adjectives"
    return ", ".join(WORD_TYPES[word_type] for word_type in point.get("attaches", []))


def parse_attaches(text: str) -> list[str]:
    # Back from the Your cards table, where it's typed as text.
    text = text.lower()
    return [word_type for word_type in WORD_TYPES if word_type in text]


def render_flashcard(card: dict, show_back: bool, deck: dict | None = None, seed: str = "") -> None:
    # With the deck, a word's back also shows which reading each of its
    # kanji uses -- seen on every review, not just while in Learn. A
    # grammar point needs the deck for a word to go with it, picked by
    # `seed` so it stays the same word until the card's answered.
    if card["kind"] == "grammar":
        render_grammar_card(card, pick_word(deck, card, f"{card['id']}:{seed}") if deck else None, show_back)
        return
    back = ""
    if show_back:
        if has_distinct_reading(card):
            back += f'<div class="flashcard-reading">{html.escape(card["reading"])}</div>'
        back += f'<div class="flashcard-meaning">{html.escape(card["meaning"])}</div>'
        if card.get("pos"):
            back += f'<div class="flashcard-pos">{html.escape(card["pos"])}</div>'
        breakdown = kanji_breakdown(deck, card) if deck else ""
        if breakdown:
            back += f'<div class="flashcard-pos" lang="ja">{html.escape(breakdown)}</div>'
        # Kanji: meaning first, then each kind of reading, for reference.
        for field, label in (("onyomi", "On"), ("kunyomi", "Kun")):
            if card.get(field):
                readings = html.escape(display_readings(card[field]))
                back += f'<div class="flashcard-kanji-reading" lang="ja"><span>{label}</span>{readings}</div>'
        # The user's own note (a mnemonic, say), and their drawing over the
        # front (the same faint front it was drawn over), last.
        if card.get("note"):
            back += f'<div class="flashcard-note">{html.escape(card["note"])}</div>'
        drawing = load_drawing(card["id"])
        if drawing:
            # Sized like the faint front in the drawing box: 80% of the
            # square, less for a longer word.
            front_size = min(128, 144 // max(1, len(card["front"])))
            back += (
                f'<div class="flashcard-drawing"><span lang="ja" style="font-size: {front_size}px">'
                f'{html.escape(card["front"])}</span>'
                f'<img alt="Your drawing" src="data:image/png;base64,{base64.b64encode(drawing).decode()}"></div>'
            )
    st.markdown(
        f'<div class="flashcard">'
        f'<div class="flashcard-kind">{KIND_LABELS[card["kind"]]}</div>'
        f'<div class="flashcard-front" lang="ja">{html.escape(card["front"])}</div>'
        f"{back}</div>",
        unsafe_allow_html=True,
    )


def answer_summary(card: dict) -> str:
    # The whole back of a card on one line, for the typed-mode verdict.
    if card.get("form_reading"):  # a grammar point, as typed_prompt asked it
        return f"{card['form_reading']} · ～{card['front']} {card['meaning']}"
    parts = [card["reading"] if has_distinct_reading(card) else "", card["meaning"]]
    if card.get("onyomi"):
        parts.append(f"on {display_readings(card['onyomi'])}")
    if card.get("kunyomi"):
        parts.append(f"kun {display_readings(card['kunyomi'])}")
    return " · ".join(part for part in parts if part)


def step_answer(card: dict, step: str) -> str:
    # The right answer for one typed part, shown when it's missed.
    if step == "form":
        return card["form_reading"]
    return display_readings(card[step]) if step in ("onyomi", "kunyomi") else card[step]


STEP_NAMES = {"reading": "Reading", "meaning": "Meaning", "onyomi": "On'yomi", "kunyomi": "Kun'yomi", "form": "Form"}


ADD_FIELD_KEYS = {
    "front": "japanese_add_front",
    "reading": "japanese_add_reading",
    "onyomi": "japanese_add_onyomi",
    "kunyomi": "japanese_add_kunyomi",
    "pos": "japanese_add_pos",
}


def apply_add_fix(index: int) -> None:
    # "Use ..." button on a spelling-check warning: puts the suggestion in
    # its field (a callback, so it lands before the field is drawn again)
    # and drops just that warning, keeping any others. Once none are left,
    # the next "Add card" re-checks and adds.
    pending = st.session_state["_japanese_add_issues"]
    issue = pending["issues"].pop(index)
    st.session_state[ADD_FIELD_KEYS[issue["field"]]] = issue["fix"]
    pending["values"][issue["field"]] = issue["fix"]
    if not pending["issues"]:
        st.session_state.pop("_japanese_add_issues", None)


def practice_card(deck: dict, kinds: list[str], filter_name: str, set_name: str) -> tuple[dict | None, int, int]:
    # Practice goes through the chosen deck (and set, e.g. picked cards) in a
    # shuffled order, then reshuffles and goes round again, forever. Returns
    # (card, its 1-based place in this round, cards in the round). The order
    # is rebuilt when the filter or set changes or a card in it has gone.
    picked = set(deck["settings"].get("picked", []))
    cards = {
        card["id"]: card for card in deck["cards"]
        if card["kind"] in kinds and in_practice_set(card, set_name, picked, today_jst())
    }
    filter_name = f"{filter_name} / {set_name}"
    if not cards:
        return None, 0, 0
    state = st.session_state.get("japanese_practice")
    if (
        not state
        or state["filter"] != filter_name
        or set(state["order"]) != set(cards)
        or state["position"] >= len(state["order"])
    ):
        order = list(cards)
        random.shuffle(order)
        # Don't start a new round on the card the last one just ended with.
        if state and len(order) > 1 and state["order"] and order[0] == state["order"][-1]:
            order.append(order.pop(0))
        state = {"filter": filter_name, "order": order, "position": 0}
        st.session_state["japanese_practice"] = state
    return cards[state["order"][state["position"]]], state["position"] + 1, len(state["order"])


def advance_practice() -> None:
    st.session_state["japanese_practice"]["position"] += 1


def reading_label(uses: dict | None) -> str:
    # "kun た(べる)", or "probably on ガク" when it's a best guess.
    if uses is None:
        return "reading not matched"
    label = f"{uses['kind']} {display_readings(uses['reading'])}"
    return label if uses["sure"] else f"probably {label}"


def render_drawing(card: dict, expanded: bool = False) -> None:
    # Draw a picture mnemonic over the card's front. Saved for the card and
    # shown on its back from then on; saving it blank removes it.
    has_drawing = load_drawing(card["id"]) is not None
    with st.expander("✏️ Edit your drawing" if has_drawing else "✏️ Draw a mnemonic", expanded=expanded):
        saved = drawing_box(f"japanese_drawing_{card['id']}", card["front"], load_drawing(card["id"]),
                            TEXT_COLOR, ACCENT_COLOR)
        st.caption("Draw over it with a mouse, pen or finger, then Save drawing. It shows on the back of the card.")
    if saved is not None:
        save_drawing(card["id"], saved)
        st.toast("Drawing saved." if saved else "Drawing removed.")
        st.rerun()


def render_learn(deck: dict) -> None:
    # Cards new to the user, one at a time with everything showing and
    # nothing graded, for as long as they like. "Got it" moves one into the
    # reviews. Only shown while there's something to learn.
    cards = learning_cards(deck)
    if not cards:
        # The last one just went into the reviews: Learn holds its place
        # until the next visit, so the page doesn't slide Review up under
        # where it was.
        if st.session_state.get("_previous_page") != st.session_state.get("_current_page"):
            st.session_state.pop("japanese_learn_emptied", None)
        if st.session_state.get("japanese_learn_emptied"):
            st.subheader("Learn")
            st.caption("All learned. They're in your reviews now.")
            st.divider()
        return
    st.session_state.pop("japanese_learn_emptied", None)
    st.subheader("Learn")
    position = st.session_state.get("japanese_learn_position", 0) % len(cards)
    card = cards[position]
    st.caption(f"Card {position + 1} of {len(cards)} to learn・take your time. "
               "“Got it” moves a card into your reviews.")
    render_flashcard(card, show_back=True, deck=deck)
    # Readings stick through words already known, so a kanji shows the
    # deck's words written with it, and which reading each one uses; a
    # word shows its kanji and their readings.
    if card["kind"] == "kanji":
        uses = words_using(deck, card)
        if uses:
            st.markdown("**Your words with it:** " + " · ".join(
                f"<span lang='ja'>{html.escape(use['card']['front'])}</span>"
                + (f" ({html.escape(use['card']['reading'])})" if has_distinct_reading(use["card"]) else "")
                + f" <small>{html.escape(reading_label(use['uses']))}</small>"
                for use in uses
            ), unsafe_allow_html=True)
        else:
            st.caption("None of your words use it yet. Adding a few is the best way to make its readings stick.")
        st.caption(RULES_OF_THUMB)
    elif card["kind"] == "grammar":
        words = fitting_words(deck, card)[:6]
        if words:
            st.markdown("**On your words:** " + " · ".join(
                f"<span lang='ja'>{html.escape(conjugate(card, word)['front'])}</span>" for word in words
            ), unsafe_allow_html=True)
    else:
        kanji_cards = kanji_in(deck, card)
        if kanji_cards:
            st.markdown("**Its kanji:** " + " · ".join(
                f"<span lang='ja'>{html.escape(kanji['front'])}</span> {html.escape(kanji['meaning'])} "
                f"<small>{html.escape(reading_label(reading_in_word(kanji, card['front'], card['reading'] or card['front'])))}</small>"
                for kanji in kanji_cards
            ), unsafe_allow_html=True)
    # A mnemonic, a story, a sentence: saved as it's typed (on leaving the
    # box), and shown on the back of the card in reviews too.
    note = st.text_area(
        "Your note", value=card["note"], key=f"japanese_learn_note_{card['id']}", height=68,
        placeholder="A mnemonic, a story, a sentence -- anything that helps it stick",
    ).strip()
    if note != card["note"]:
        update_card(deck, card["id"], note=note)
        save_deck(deck)
    if card["kind"] != "grammar":
        render_drawing(card)
    back_column, next_column, got_column = st.columns(3)
    if back_column.button("← Back", key="japanese_learn_back", width="stretch", disabled=len(cards) < 2):
        st.session_state["japanese_learn_position"] = position - 1
        st.rerun()
    if next_column.button("Next →", key="japanese_learn_next", width="stretch", disabled=len(cards) < 2):
        st.session_state["japanese_learn_position"] = position + 1
        st.rerun()
    if got_column.button("Got it", key="japanese_learn_got_it", width="stretch",
                         help="Moves it into your reviews. Its first review is tomorrow."):
        set_learning(deck, card["id"], False)
        save_deck(deck)
        st.session_state["japanese_learn_emptied"] = len(cards) == 1
        # The next card slides into this place.
        st.session_state["japanese_learn_position"] = position
        st.toast(f"{card['front']} is in your reviews now.")
        st.rerun()
    st.divider()


def render_review(deck: dict) -> None:
    # Review: the page's primary content, so always visible (house style --
    # secondary sections go in expanders below).
    st.subheader("Review")
    filter_column, toggle_column = st.columns([3, 2], vertical_alignment="bottom")
    with filter_column:
        review_filter = st.segmented_control(
            "Deck", list(DECK_FILTERS), default="All", required=True, key="japanese_review_filter"
        )
    with toggle_column:
        # Practice: cycles through every card (of the chosen deck) for as
        # long as wanted, without touching the SRS schedule -- for when
        # nothing's due but there's time to keep going. Session-only: a
        # fresh visit starts back on real reviews.
        practice_mode = st.toggle(
            "Practice",
            key="japanese_practice_toggle",
            help="Go through all your cards as many times as you like. Doesn't change when cards are due.",
        )
        # realkana-style: type the answer and have it checked, instead of
        # revealing it and grading yourself. Saved with the deck, so it
        # stays how it was left.
        typed_mode = st.toggle(
            "Type answers",
            value=deck["settings"].get("typed_answers", False),
            key="japanese_typed_toggle",
            help="Type the reading and meaning and they're checked for you. "
            "Romaji turns into kana. Grammar: put the word and the ending together.",
        )
        # Daily reviews in a random order rather than oldest-due first. On by
        # default and saved with the deck; Practice always shuffles anyway.
        shuffle_mode = st.toggle(
            "Shuffle",
            value=deck["settings"].get("shuffle_reviews", True),
            key="japanese_shuffle_toggle",
            disabled=practice_mode,
            help="Show due cards in a random order. Cards you get wrong still come back after the rest.",
        )
    if (
        typed_mode != deck["settings"].get("typed_answers", False)
        or shuffle_mode != deck["settings"].get("shuffle_reviews", True)
    ):
        deck["settings"]["typed_answers"] = typed_mode
        deck["settings"]["shuffle_reviews"] = shuffle_mode
        save_deck(deck)

    kinds = DECK_FILTERS[review_filter]
    # One seed per visit: the shuffled order holds still across reruns (and
    # the deck filter), and a fresh visit gets a new one.
    shuffle_seed = st.session_state.setdefault("japanese_shuffle_seed", uuid.uuid4().hex) if shuffle_mode else None
    due = due_cards(deck, kinds, shuffle_seed)
    reviewed_today = deck["reviews"].get(today_jst().isoformat(), 0)
    card = None
    if practice_mode:
        # Which cards to go round. Picked ones are ticked under Your cards.
        picked_count = len(deck["settings"].get("picked", []))
        practice_set = st.selectbox(
            "Practice", PRACTICE_SETS, key="japanese_practice_set",
            format_func=lambda name: f"{name} ({picked_count})" if name == "Picked cards" else name,
            help="Picked cards are the ones ticked under Your cards. Trouble cards are ones you've missed twice "
            "or more. They stay here until they stick. Cards in Learn are the ones you haven't marked "
            "“Got it” yet, tested before they go into your reviews. Verbs, adjectives and nouns go by part of speech.",
        )
        card, position, total = practice_card(deck, kinds, review_filter, practice_set)
        # A new word for a grammar point each time round.
        word_seed = f"practice:{position}:{st.session_state['japanese_practice']['order'][0]}" if card else ""
        if card:
            st.caption(f"Practice · card {position} of {total} · doesn't change when cards are due")
    else:
        st.caption(f"{len(due)} due · {reviewed_today} reviewed today")
        if due:
            card = due[0]
            # A new word for a grammar point after each answer.
            word_seed = f"{card['reps']}:{card['lapses']}:{card['last_reviewed']}"

    # Typed mode moves straight on to the next card after an answer, so the
    # verdict on the one just answered shows here, above it.
    # A card is typed in parts (vocab: reading, then meaning); this is how
    # far into the current card that's got.
    # The last card's verdict is hidden while one is part-way through, so the
    # marks shown are all for the card on screen.
    progress = st.session_state.get("japanese_step")
    if card is None or not progress or progress["key"] != (card["id"], practice_mode):
        progress = {"key": (card["id"], practice_mode) if card else None, "parts": []}
    last_result = st.session_state.get("japanese_last_result")
    # A grammar point is typed on its word; one with no word to go on is
    # shown and graded by hand instead.
    asked = card
    if card is not None and card["kind"] == "grammar":
        word = pick_word(deck, card, f"{card['id']}:{word_seed}")
        asked = typed_prompt(card, word) if word else None
    if typed_mode and last_result and not progress["parts"]:
        answered = last_result["card"]
        # A grammar point shows as it was asked: on its word.
        shown = last_result.get("shown", answered)
        # Results saved before multi-part answers existed have no "parts".
        parts = last_result.get("parts") or [{"step": None, "ok": last_result["correct"], "typed": last_result["typed"]}]
        verdict_column, override_column = st.columns([4, 1], vertical_alignment="center")
        with verdict_column:
            icon = "✅" if last_result["correct"] else "❌"
            summary = (f"{icon} **{html.escape(shown.get('form_front', shown['front']))}** — "
                       f"{html.escape(answer_summary(shown))}")
            if len(parts) == 1 and not last_result["correct"] and parts[0]["typed"]:
                summary += f" (you typed *{html.escape(parts[0]['typed'])}*)"
            st.markdown(summary)
            breakdown = kanji_breakdown(deck, answered)
            if breakdown:
                st.caption(breakdown)
            if len(parts) > 1 and not last_result["correct"]:
                st.caption(
                    " · ".join(
                        f"{STEP_NAMES[part['step']]} {'✅' if part['ok'] else '❌'}"
                        + (f" (you typed {part['typed']})" if not part["ok"] and part["typed"] else "")
                        for part in parts
                    )
                )
        # Practice answers aren't scheduled, so there's nothing to undo.
        any_typed = any(part["typed"] for part in parts)
        if not last_result["correct"] and any_typed and not last_result.get("practice"):
            with override_column:
                # For typos and answers the check was too strict about:
                # undoes the "Again" and counts it as "Good" instead.
                if st.button("I was right", key="japanese_override", width="stretch"):
                    regrade(deck, last_result["card"], "good")
                    save_deck(deck)
                    last_result["correct"] = True
                    st.rerun()

    if not deck["cards"]:
        st.write("No cards yet -- add some below.")
    elif card is None and practice_mode:
        if practice_set == "Picked cards":
            st.write("No cards picked yet. Tick some in the Pick column under Your cards.")
        elif practice_set == "Trouble cards":
            st.write("No trouble cards right now. Nothing's been missed twice without sticking since.")
        elif practice_set != "Every card":
            st.write(f"No cards in \"{practice_set}\" yet.")
        else:
            st.write(f"No {review_filter.lower()} cards yet.")
    elif card is None:
        upcoming = sorted(other["due"] for other in deck["cards"] if other["kind"] in kinds and not other["learning"])
        if upcoming:
            st.write(f"Nothing due right now. Next card is due {upcoming[0]}.")
            st.caption("Turn on **Practice** to keep going anyway.")
        elif learning_cards(deck, kinds):
            st.write("Nothing to review yet: your cards are all in Learn above.")
        else:
            st.write(f"No {review_filter.lower()} cards yet.")
    elif typed_mode and asked is not None:
        if card["kind"] == "grammar":
            render_grammar_prompt(asked)
        else:
            render_flashcard(card, show_back=False)
        steps = answer_steps(asked)
        if len(progress["parts"]) >= len(steps):  # card edited to fewer parts mid-way
            progress["parts"] = []
        step = steps[len(progress["parts"])]
        if len(steps) > 1:
            # Parts already answered for this card, each marked as it goes
            # (a miss shows the answer) -- a wrong part doesn't end the card,
            # every part still gets asked.
            done = [
                f"{STEP_NAMES[part['step']]} {'✅' if part['ok'] else '❌ ' + step_answer(asked, part['step'])}"
                for part in progress["parts"]
            ]
            st.caption(" · ".join(done + [f"Part {len(progress['parts']) + 1} of {len(steps)}"]))
        with st.form("japanese_typed_form", clear_on_submit=True, border=False):
            typed = st.text_input(
                STEP_LABELS[step],
                key="japanese_typed_answer",
                placeholder="Leave blank and press Enter if you don't know it",
            )
            checked = st.form_submit_button("Check", width="stretch")
        if checked:
            progress["parts"].append({"step": step, "ok": check_step(asked, step, typed), "typed": typed.strip()})
            st.session_state["japanese_answer_count"] = st.session_state.get("japanese_answer_count", 0) + 1
            if len(progress["parts"]) < len(steps):
                st.session_state["japanese_step"] = progress
                st.rerun()
            # Last part answered: the card counts as right only if every part was.
            correct = all(part["ok"] for part in progress["parts"])
            snapshot = dict(card)
            if practice_mode:
                advance_practice()
            else:
                review_card(deck, card["id"], "good" if correct else "again")
                save_deck(deck)
            st.session_state["japanese_last_result"] = {
                "card": snapshot,
                "correct": correct,
                "parts": progress["parts"],
                "typed": progress["parts"][0]["typed"],
                "practice": practice_mode,
                "shown": asked,
            }
            st.session_state.pop("japanese_step", None)
            st.rerun()
        # Puts the cursor back in the answer box for each new card, so a
        # review session is just type, Enter, type, Enter. The answer count
        # makes the snippet differ each time -- an unchanged one isn't re-run
        # (and in practice the same card can come straight back around).
        answer_count = st.session_state.get("japanese_answer_count", 0)
        st.html(
            f"<script>/* {card['id']} {answer_count} */"
            "setTimeout(() => document.querySelector('.st-key-japanese_typed_answer input')?.focus(), 100);"
            "</script>",
            unsafe_allow_javascript=True,
        )
    else:
        # Which card's answer is showing -- by id and mode, so answering (or
        # the queue changing under it) hides the answer for whatever's next.
        reveal_key = (card["id"], practice_mode)
        revealed = st.session_state.get("japanese_revealed") == reveal_key
        render_flashcard(card, show_back=revealed, deck=deck, seed=word_seed)

        if not revealed:
            if st.button("Show answer", key="japanese_show_answer", width="stretch"):
                st.session_state["japanese_revealed"] = reveal_key
                st.rerun()
        elif practice_mode:
            # Nothing to grade in practice -- just on to the next card.
            if st.button("Next", key="japanese_practice_next", width="stretch"):
                advance_practice()
                st.session_state.pop("japanese_revealed", None)
                st.rerun()
        else:
            # Each button shows when the card comes back if picked, like Anki.
            grade_columns = st.columns(len(GRADES))
            for column, grade in zip(grade_columns, GRADES):
                interval, _ = next_schedule(card, grade)
                with column:
                    if st.button(
                        f"{GRADE_LABELS[grade]} · {format_interval(interval)}",
                        key=f"japanese_grade_{grade}_{card['id']}",
                        width="stretch",
                    ):
                        review_card(deck, card["id"], grade)
                        save_deck(deck)
                        st.session_state.pop("japanese_revealed", None)
                        st.rerun()
        # A mnemonic can come to mind while reviewing, too.
        if revealed and card["kind"] != "grammar":
            render_drawing(card)


def render_kana(deck: dict) -> None:
    # A drill for total beginners: a kana from the sets switched on, type
    # its romaji, see if it was right, next. Not scheduled -- kana are
    # learned by going round until they're automatic. The sets and the
    # on/off switch are saved with the deck.
    settings = kana_settings(deck)
    with st.expander("Kana", expanded=settings["on"]):
        on = st.toggle("Practice kana", value=settings["on"], key="japanese_kana_on",
                       help="Hiragana and Katakana, one set at a time.")
        scripts, sets = settings["scripts"], settings["sets"]
        if on:
            scripts = st.pills("Script", list(SCRIPTS), format_func=SCRIPTS.get, selection_mode="multi",
                               default=settings["scripts"], key="japanese_kana_scripts")
            sets = st.pills("Sets", KANA_SETS, selection_mode="multi", default=settings["sets"],
                            key="japanese_kana_sets",
                            help="Each row of the kana chart. Exceptions are し, ち, つ and ふ; "
                            "combinations are kana with a small ゃ, ゅ or ょ, like きゃ.")
        if (on, scripts, sets) != (settings["on"], settings["scripts"], settings["sets"]):
            deck["settings"]["kana"] = {"on": on, "scripts": scripts, "sets": sets}
            save_deck(deck)
        if not on:
            return
        pool = kana_pool(scripts, sets)
        if not pool:
            st.write("Pick a script and at least one set.")
            return
        # The kana on screen, until it's answered or its set is switched off.
        current = st.session_state.get("japanese_kana_current")
        if current not in pool:
            current = st.session_state["japanese_kana_current"] = next_kana(pool)
        # The last answer, and a running count for this visit.
        last = st.session_state.get("japanese_kana_last")
        if last:
            line = f"{'✅' if last['ok'] else '❌'} <span class='kana-plain' lang='ja'>{last['kana']}</span> {last['romaji']}"
            if not last["ok"] and last["typed"]:
                line += f" (you typed *{html.escape(last['typed'])}*)"
            score = st.session_state.get("japanese_kana_score", [0, 0])
            st.markdown(f"{line} · {score[0]} of {score[1]} right", unsafe_allow_html=True)
        script_name = "Katakana" if "ァ" <= current["kana"][0] <= "ヶ" else "Hiragana"
        st.markdown(
            f'<div class="flashcard"><div class="flashcard-kind">{script_name}</div>'
            f'<div class="flashcard-front" lang="ja">{current["kana"]}</div></div>',
            unsafe_allow_html=True,
        )
        with st.form("japanese_kana_form", clear_on_submit=True, border=False):
            typed = st.text_input("Romaji", key="japanese_kana_answer",
                                  placeholder="Leave blank and press Enter if you don't know it")
            checked = st.form_submit_button("Check", width="stretch")
        if checked:
            ok = check_kana(current, typed)
            score = st.session_state.get("japanese_kana_score", [0, 0])
            st.session_state["japanese_kana_score"] = [score[0] + ok, score[1] + 1]
            st.session_state["japanese_kana_last"] = {**current, "ok": ok, "typed": typed.strip()}
            st.session_state["japanese_kana_current"] = next_kana(pool, current["kana"])
            st.rerun()
        # Back in the box after each answer (only then, so it doesn't pull
        # the cursor away from Review's typed answers on arriving).
        answered = st.session_state.get("japanese_kana_score", [0, 0])[1]
        if answered:
            st.html(
                f"<script>/* {answered} */"
                "setTimeout(() => document.querySelector('.st-key-japanese_kana_answer input')?.focus(), 100);"
                "</script>",
                unsafe_allow_javascript=True,
            )


def render_add_cards(deck: dict) -> None:
    # Adding cards: open by default only while the deck is still empty.
    with st.expander("Add cards", expanded=not deck["cards"]):
        add_kind = st.segmented_control(
            "Type", KINDS, format_func=KIND_LABELS.get, default="vocab", required=True, key="japanese_add_kind"
        )
        # Cleared here, before the fields exist, after a card is added --
        # a widget's value can't be changed once it's been drawn this run.
        if st.session_state.pop("_reset_japanese_add", False):
            for key in (
                "japanese_add_lookup",
                "japanese_add_front",
                "japanese_add_reading",
                "japanese_add_meaning",
                "japanese_add_onyomi",
                "japanese_add_kunyomi",
                "japanese_add_pos",
                "japanese_add_note",
            ):
                st.session_state[key] = ""
            st.session_state["japanese_add_attaches"] = list(WORD_TYPES)
            st.session_state.pop("_japanese_filled_from", None)

        is_vocab = add_kind == "vocab"
        is_grammar = add_kind == "grammar"
        if is_grammar:
            # Grammar points aren't looked up anywhere: the starter set
            # covers the basics, the rest are typed in.
            missing_starters = [ending for ending, _ in STARTER_POINTS
                                if not find_duplicate(deck, "grammar", ending)]
            if missing_starters:
                if st.button(f"Add the state-of-being set ({len(missing_starters)} point{'s' if len(missing_starters) != 1 else ''})",
                             key="japanese_add_starter_grammar",
                             help="だ, です, じゃない, じゃありません, だった, でした, じゃなかった, じゃありませんでした: "
                             "the forms nouns and na-adjectives take. Edit or delete them under Your cards."):
                    had = {card["id"] for card in deck["cards"]}
                    added = add_starter_points(deck)
                    save_deck(deck)
                    new_card_ids().update(card["id"] for card in deck["cards"] if card["id"] not in had)
                    st.toast(f"Added {added} grammar points.")
                    st.rerun()
            lookup = ""
        else:
            lookup = st.text_input(
                "Look up on Jisho" if is_vocab else "Look up kanji",
                key="japanese_add_lookup",
                placeholder="Kanji, kana, romaji, or English" if is_vocab else "A kanji, or a word to pick its kanji from",
            )
        candidates = []
        if lookup.strip():
            try:
                candidates = jisho_lookup(lookup) if is_vocab else kanji_lookup(lookup)
                if not candidates:
                    st.caption("No matches -- fill the card in by hand below.")
            except (urllib.error.URLError, TimeoutError, ValueError):
                source_name = "Jisho" if is_vocab else "kanjiapi.dev"
                st.caption(f"Couldn't reach {source_name} right now -- fill the card in by hand below.")
        if candidates:
            in_deck = {card["front"] for card in deck["cards"] if card["kind"] == add_kind}

            def candidate_label(index: int) -> str:
                candidate = candidates[index]
                if is_vocab:
                    label = candidate["front"]
                    if candidate["reading"]:
                        label += f"【{candidate['reading']}】"
                    label += f" — {candidate['meaning']}"
                    if candidate.get("pos"):
                        label += f" · {candidate['pos']}"
                    if candidate["common"]:
                        label += " · common"
                else:
                    readings = " · ".join(
                        f"{name}: {value}" for name, value in (("on", candidate["on"]), ("kun", candidate["kun"])) if value
                    )
                    label = f"{candidate['front']} — {candidate['meaning']}" + (f" ({readings})" if readings else "")
                if candidate["front"] in in_deck:
                    label += " · already added"
                return label

            pick = st.radio(
                "Matches", range(len(candidates)), format_func=candidate_label, key=f"japanese_pick_{add_kind}_{lookup}"
            )
            # Fill the card in from the pick -- once per pick, so edits made
            # to the fields afterwards aren't overwritten on the next rerun.
            filled_from = (add_kind, lookup, pick)
            if st.session_state.get("_japanese_filled_from") != filled_from:
                chosen = candidates[pick]
                st.session_state["japanese_add_front"] = chosen["front"]
                st.session_state["japanese_add_reading"] = chosen.get("reading", "")
                st.session_state["japanese_add_meaning"] = chosen["meaning"]
                st.session_state["japanese_add_onyomi"] = chosen.get("on", "")
                st.session_state["japanese_add_kunyomi"] = chosen.get("kun", "")
                st.session_state["japanese_add_pos"] = chosen.get("pos", "")
                st.session_state["_japanese_filled_from"] = filled_from

        front = st.text_input(
            "Ending" if is_grammar else "Word" if is_vocab else "Kanji",
            key="japanese_add_front",
            placeholder="e.g. じゃなかった" if is_grammar else None,
        )
        reading = (
            st.text_input(
                "Reading (hiragana)",
                key="japanese_add_reading",
                help="Can be left blank for words written in kana -- they're quizzed on their meaning instead.",
            )
            if is_vocab
            else ""
        )
        meaning = st.text_input("Meaning", key="japanese_add_meaning",
                                placeholder="e.g. wasn't (casual)" if is_grammar else None)
        attaches = (
            st.multiselect(
                "Goes on", list(WORD_TYPES), format_func=WORD_TYPES.get, key="japanese_add_attaches",
                default=list(WORD_TYPES) if "japanese_add_attaches" not in st.session_state else None,
                help="Which of your words it's practiced on, by their part of speech.",
            )
            if is_grammar
            else []
        )
        pos = (
            st.text_input(
                "Part of speech",
                key="japanese_add_pos",
                placeholder="e.g. Noun, Godan verb, I-adjective",
                help="Filled in from Jisho. Optional. It shows on the back of the card, and searching your cards "
                "for it (\"verb\") finds every card with it.",
            )
            if is_vocab
            else ""
        )
        note = st.text_input(
            "Note", key="japanese_add_note", placeholder="Optional -- a mnemonic, a story, anything that helps",
            help="Your own note. It shows in Learn and on the back of the card.",
        )
        onyomi = kunyomi = ""
        if add_kind == "kanji":
            # Filled in from the lookup with every reading KANJIDIC lists --
            # trim them to the ones you know; typed review accepts any one.
            reading_help = "Separate several with 、 or commas. Leave blank if the kanji has none."
            onyomi = st.text_input("On'yomi", key="japanese_add_onyomi", help=reading_help)
            kunyomi = st.text_input(
                "Kun'yomi",
                key="japanese_add_kunyomi",
                help=reading_help + " A dot marks where the okurigana starts (つよ.い).",
            )
        # Possible typos found by the spelling check on the last "Add card"
        # click -- only kept while the fields still hold what was checked;
        # editing any of them by hand drops the warnings (the next "Add
        # card" checks again).
        current_values = {
            "kind": add_kind,
            "front": front.strip(),
            "reading": reading.strip(),
            "meaning": meaning.strip(),
            "onyomi": onyomi.strip(),
            "kunyomi": kunyomi.strip(),
            "pos": pos.strip(),
            "attaches": attaches,
        }
        pending = st.session_state.get("_japanese_add_issues")
        if pending and pending["values"] != current_values:
            st.session_state.pop("_japanese_add_issues", None)
            pending = None

        # New to you: studied in Learn first. Already known: straight into
        # reviews, as before. Remembered for the next card.
        add_as = st.segmented_control(
            "This card is", ["Already known", "New to me"], required=True, key="japanese_add_as",
            default="New to me" if deck["settings"].get("add_as_learning") else "Already known",
            help="New cards go to Learn, to study at your own pace before they're reviewed.",
        )
        if (add_as == "New to me") != deck["settings"].get("add_as_learning", False):
            deck["settings"]["add_as_learning"] = add_as == "New to me"
            save_deck(deck)
        add_clicked = st.button("Add card", key="japanese_add_button")
        add_anyway = False
        if pending:
            for index, issue in enumerate(pending["issues"]):
                warning_column, fix_column = st.columns([4, 1], vertical_alignment="center")
                with warning_column:
                    st.markdown(f"⚠️ {html.escape(issue['message'], quote=False)}")
                if issue["fix"]:
                    with fix_column:
                        st.button(
                            f"Use {issue['fix']}",
                            key=f"japanese_fix_{index}",
                            on_click=apply_add_fix,
                            args=(index,),
                            width="stretch",
                        )
            add_anyway = st.button("Add anyway", key="japanese_add_anyway", help="Add the card exactly as typed")

        if add_clicked or add_anyway:
            front_name = "ending" if is_grammar else "word" if is_vocab else "kanji"
            if not front.strip() or not meaning.strip():
                st.toast(f"A card needs both the {front_name} and its meaning.", icon="⚠️")
            elif is_grammar and not attaches:
                st.toast("Pick what it goes on.", icon="⚠️")
            elif find_duplicate(deck, add_kind, front):
                st.toast(f"{front.strip()} is already in your {KIND_LABELS[add_kind].lower()} cards.", icon="⚠️")
            else:
                issues = []
                if add_clicked and not is_grammar:
                    # Checked against Jisho / KANJIDIC for typos first; if
                    # neither can be reached, the card's just added as usual.
                    try:
                        issues = check_new_card(add_kind, front, reading, onyomi, kunyomi)
                    except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
                        issues = []
                if issues:
                    st.session_state["_japanese_add_issues"] = {"values": current_values, "issues": issues}
                    st.rerun()
                if is_grammar:
                    card = add_grammar_point(deck, front, meaning, attaches, note, learning=add_as == "New to me")
                else:
                    card = add_card(deck, add_kind, front, reading, meaning, onyomi, kunyomi, pos, note,
                                    learning=add_as == "New to me")
                save_deck(deck)
                new_card_ids().add(card["id"])
                st.session_state.pop("_japanese_add_issues", None)
                st.session_state["_reset_japanese_add"] = True
                # Typed out under the button on the next run, like Meal
                # Receipts' "[Logged ...]" line -- stashed rather than typed
                # here, since st.rerun() below would discard it unseen.
                reading_note = f" ({card['reading']})" if has_distinct_reading(card) else ""
                kanji_readings = "".join(
                    f" · {label} {display_readings(card[field])}"
                    for field, label in (("onyomi", "on"), ("kunyomi", "kun"))
                    if card[field]
                )
                st.session_state["_japanese_add_confirmation"] = (
                    f"[Added {'～' if is_grammar else ''}{card['front']}{reading_note}: {card['meaning']}{kanji_readings}"
                    + (" · in Learn]" if card["learning"] else "]")
                )
                st.rerun()
        else:
            # Popped so it types out once, not on every later rerun.
            pending_confirmation = st.session_state.pop("_japanese_add_confirmation", None)
            if pending_confirmation:
                typewriter(pending_confirmation)


def new_card_ids() -> set[str]:
    # Cards added on this visit, picked out in Your cards until the page is
    # left or Your cards is closed.
    if st.session_state.get("_previous_page") != st.session_state.get("_current_page"):
        st.session_state["japanese_new_cards"] = set()
    return st.session_state.setdefault("japanese_new_cards", set())


def render_your_cards(deck: dict) -> None:
    # Lookup of everything already in the deck, editable in place.
    # Keyed and tracked, so it stays open through the reruns its own edits
    # cause -- ticking Learn adds the Learn section above it, which would
    # otherwise rebuild it closed.
    your_cards = st.expander("Your cards", key="japanese_your_cards", on_change="rerun")
    new_ids = new_card_ids()
    if st.session_state.get("_japanese_your_cards_open") and not your_cards.open:
        new_ids.clear()
    st.session_state["_japanese_your_cards_open"] = your_cards.open
    with your_cards:
        # Half the row each: the four Deck buttons need about 300px, more
        # than two fifths of the expander gave them.
        search_columns = st.columns(2, vertical_alignment="bottom")
        with search_columns[0]:
            query = st.text_input("Search", placeholder="Word, reading, or meaning", key="japanese_search")
        with search_columns[1]:
            lookup_filter = st.segmented_control(
                "Deck", list(DECK_FILTERS), default="All", required=True, key="japanese_lookup_filter"
            )
        matches = search_cards(deck, query, DECK_FILTERS[lookup_filter])
        if not deck["cards"]:
            st.write("No cards yet.")
        elif not matches:
            st.write("No cards match.")
        else:
            picked = set(deck["settings"].get("picked", []))
            # Cards Jisho had no part of speech for when filling them in:
            # marked until one's typed in by hand.
            not_found = set(deck["settings"].get("pos_not_found", []))
            table = pd.DataFrame(
                [
                    {
                        "id": card["id"],
                        "picked": card["id"] in picked,
                        "learning": card["learning"],
                        "missing": "⚠" if card["id"] in not_found and not card["pos"] else "",
                        "kind": KIND_LABELS[card["kind"]],
                        "front": card["front"],
                        "reading": card["reading"],
                        "onyomi": card["onyomi"],
                        "kunyomi": card["kunyomi"],
                        "meaning": card["meaning"],
                        # A grammar point's word types sit in the same column.
                        "pos": attaches_label(card) if card["kind"] == "grammar" else card["pos"],
                        "note": card["note"],
                        "misses": card["lapses"],
                        "due": "In Learn" if card["learning"] else card["due"],
                    }
                    for card in matches
                ]
            ).set_index("id")
            # Keyed by the filters too: a data_editor's pending edits are
            # tied to row positions, so a new search gets a fresh editor
            # instead of replaying edits onto whatever rows moved into place.
            editor_key = f"japanese_editor_{lookup_filter}_{query}"
            # Room for the table's hover toolbar, which sits just above its
            # top-right corner -- otherwise right over the Deck buttons.
            st.space(32)
            flagged = int((table["missing"] != "").sum())
            column_order = [name for name in table.columns if name != "missing" or flagged]
            # Streamlit only colours cells that can't be edited, so the mark
            # sits in a narrow column of its own, near the left where it's
            # seen without scrolling the table sideways.
            # Cards just added have their Type and Next review cells lit up.
            shown_table = table.style.map(
                lambda value: f"background-color: {ACCENT_COLOR}40" if value else "", subset=["missing"]
            ).apply(
                lambda row: [f"background-color: {ACCENT_COLOR}66" if row.name in new_ids else ""] * len(row),
                axis=1, subset=["kind", "due"],
            )
            edited = st.data_editor(
                shown_table,
                num_rows="delete",
                hide_index=True,
                width="stretch",
                key=editor_key,
                column_order=column_order,
                disabled=["kind", "due", "missing", "misses"],
                column_config={
                    "picked": st.column_config.CheckboxColumn(
                        "Pick", help="Practice it with Practice → Picked cards. Doesn't change when it's due."
                    ),
                    "learning": st.column_config.CheckboxColumn(
                        "Learn", help="In Learn, not reviewed yet. Tick to send a forgotten card back there."
                    ),
                    "kind": "Type",
                    "front": "Word / kanji / ending",
                    "reading": st.column_config.TextColumn("Reading", help="Vocab only"),
                    "onyomi": st.column_config.TextColumn("On'yomi", help="Kanji only"),
                    "kunyomi": st.column_config.TextColumn("Kun'yomi", help="Kanji only"),
                    "meaning": "Meaning",
                    "pos": st.column_config.TextColumn(
                        "Part of speech", help="Vocab: its part of speech. Grammar: what it goes on (Nouns, Na-adjectives)"
                    ),
                    "note": st.column_config.TextColumn("Note", help="Your own note, e.g. a mnemonic"),
                    "missing": st.column_config.TextColumn(" ", width=36, help="No part of speech on Jisho -- type one in"),
                    "misses": st.column_config.NumberColumn(
                        "Misses", help="Times you've answered Again. Twice or more makes it a trouble card "
                        "until it sticks", width="small"),
                    "due": "Next review",
                },
            )
            # Every tick or edit saves and redraws the table, which starts it
            # back at the top. So where it was scrolled is noted on each click
            # or key in it, and put back once it's redrawn (for a few
            # seconds, unless it's scrolled by hand meanwhile).
            st.html(
                """<script>
                if (!window._yourCardsScrollInstalled) {
                    window._yourCardsScrollInstalled = true;
                    const table = ".st-key-japanese_your_cards [data-testid=stDataFrame]";
                    const scroller = () => document.querySelector(table + " .dvn-scroller");
                    let saved = null;
                    const remember = event => {
                        const box = scroller();
                        if (!box || !event.target.closest || !event.target.closest(table)) return;
                        saved = { top: box.scrollTop, left: box.scrollLeft, until: Date.now() + 5000 };
                        requestAnimationFrame(restore);
                    };
                    const restore = () => {
                        if (!saved || Date.now() > saved.until) { saved = null; return; }
                        const box = scroller();
                        if (box && box.scrollTop === 0 && box.scrollLeft === 0 && (saved.top || saved.left)) {
                            box.scrollTop = saved.top;
                            box.scrollLeft = saved.left;
                        }
                        requestAnimationFrame(restore);
                    };
                    document.addEventListener("pointerdown", remember, true);
                    document.addEventListener("keydown", remember, true);
                    document.addEventListener("wheel", event => {
                        if (event.target.closest && event.target.closest(table)) saved = null;
                    }, true);
                }
                </script>""",
                unsafe_allow_javascript=True,
            )
            st.caption(f"{len(matches)} card(s) · {len(picked)} picked")
            st.caption("Changes save as you make them. Select rows and press Delete to remove cards.")
            if flagged:
                st.caption(f"⚠ Jisho had no part of speech for {flagged} card{'s' if flagged != 1 else ''}. "
                           "Type them into the Part of speech column by hand.")
            # Stations from Budget that OpenStreetMap had no Japanese name
            # for: listed until dismissed, to add by hand if wanted.
            missed_stations = deck["settings"].get("stations_not_found", [])
            if missed_stations:
                missed_column, dismiss_column = st.columns([5, 1], vertical_alignment="center")
                missed_column.caption("Couldn't find these stations from your fares on OpenStreetMap: "
                                      + ", ".join(missed_stations) + ". Add them by hand if you like.")
                if dismiss_column.button("OK", key="japanese_dismiss_stations", width="stretch"):
                    deck["settings"]["stations_not_found"] = []
                    save_deck(deck)
                    st.rerun()
            pick_column, clear_column, fill_column = st.columns([2, 2, 3])
            # Pick every card the search and Deck filter show (e.g. search
            # "verb"), or start the picks over.
            if pick_column.button(f"Pick all {len(matches)} shown", key="japanese_pick_shown", width="stretch"):
                deck["settings"]["picked"] = sorted(picked | {card["id"] for card in matches})
                save_deck(deck)
                st.session_state.pop(editor_key, None)
                st.rerun()
            if clear_column.button("Clear picks", key="japanese_clear_picks", disabled=not picked, width="stretch"):
                deck["settings"]["picked"] = []
                save_deck(deck)
                st.session_state.pop(editor_key, None)
                st.rerun()
            # Vocab cards made before parts of speech were added: looked up
            # on Jisho in one go. Ones Jisho can't match stay blank, marked,
            # and aren't tried again.
            missing = [card for card in deck["cards"]
                       if card["kind"] == "vocab" and not card["pos"] and card["id"] not in not_found]
            if missing and fill_column.button(
                f"Fill in parts of speech ({len(missing)})",
                key="japanese_fill_pos",
                width="stretch",
                help="Looks up each vocab card without one on Jisho. Cards it can't match are marked, to fill in by hand.",
            ):
                filled = 0
                try:
                    with st.spinner("Looking them up on Jisho..."):
                        for card in missing:
                            card["pos"] = part_of_speech_for(card["front"], card["reading"])
                            filled += bool(card["pos"])
                            if not card["pos"]:
                                not_found.add(card["id"])
                except (urllib.error.URLError, TimeoutError, ValueError):
                    st.toast("Couldn't reach Jisho right now. Try again later.", icon="⚠️")
                deck["settings"]["pos_not_found"] = sorted(not_found)
                save_deck(deck)
                st.toast(f"Filled in {filled} of {len(missing)}.")
                st.rerun()
            # Same as Meal Receipts' Entries: saved as soon as anything in
            # the table changes, no Save button.
            editor_changes = st.session_state.get(editor_key, {})
            if any(editor_changes.get(part) for part in ("edited_rows", "deleted_rows")):
                deleted = set(table.index) - set(edited.index)
                delete_cards(deck, deleted)
                # Picks for the cards on show follow their ticks; others stay.
                # Sending a card to Learn picks it too.
                ticked = set(edited.index[edited["picked"].fillna(False).astype(bool)])
                learning = edited["learning"].fillna(False).astype(bool)
                ticked |= set(edited.index[learning & ~table.loc[edited.index, "learning"]])
                deck["settings"]["picked"] = sorted((picked - set(table.index)) | ticked)
                clashes = []
                for card_id, row in edited.iterrows():
                    kind = KINDS[list(KIND_LABELS.values()).index(row["kind"])]
                    new_front = str(row["front"]) if pd.notna(row["front"]) else ""
                    if find_duplicate(deck, kind, new_front, exclude_id=card_id):
                        clashes.append(row["front"])
                        continue
                    update_card(
                        deck,
                        card_id,
                        front=row["front"],
                        reading=row["reading"] if kind == "vocab" else "",
                        meaning=row["meaning"],
                        onyomi=row["onyomi"] if kind == "kanji" else "",
                        kunyomi=row["kunyomi"] if kind == "kanji" else "",
                        pos=row["pos"] if kind == "vocab" else "",
                        note=row["note"],
                    )
                    if kind == "grammar":
                        new_attaches = parse_attaches(str(row["pos"]) if pd.notna(row["pos"]) else "")
                        for card in deck["cards"]:
                            if card["id"] == card_id:
                                card["attaches"] = new_attaches
                    set_learning(deck, card_id, bool(row["learning"]))
                save_deck(deck)
                del st.session_state[editor_key]
                message = "Saved."
                if deleted:
                    message += f" Deleted {len(deleted)} card(s)."
                if clashes:
                    message += f" Skipped renaming to {', '.join(clashes)} (already in your cards)."
                st.toast(message)
                st.rerun()


# Places to study further, kept short. Links checked 2026-10-08.
RESOURCES = [
    ("Tae Kim's Guide to Japanese Grammar", "https://guidetojapanese.org/learn/grammar",
     "grammar from the basics up in appropriate order"),
    ("Tofugu's Japanese Grammar Index", "https://www.tofugu.com/japanese-grammar/",
     "one grammar point at a time with numerous examples"),
    ("JLPT N5 kanji on Jisho", "https://jisho.org/search/%23jlpt-n5%20%23kanji",
     "the first kanji to learn, including readings and example words"),
]


def render_resources() -> None:
    with st.expander("Further resources"):
        st.markdown("\n".join(f"- [{name}]({url}): {note}" for name, url, note in RESOURCES))


deck = load_deck()
# Stations logged on Budget's fares become vocab cards in Learn, a few
# lookups at a time.
pending_stations = new_stations(deck)
if pending_stations:
    with st.spinner("Adding stations from your fares..."):
        added_stations = add_station_cards(deck, pending_stations)
    save_deck(deck)
    if added_stations:
        st.toast(f"Added {added_stations} station{'s' if added_stations != 1 else ''} from your fares to Learn.")

with st.container(key="main_body"):
    # Learn in a box of its own: a kanji there shows more than a word does,
    # and without it everything below would count as new on the next card,
    # running the answer box's focus again (scrolling down to it).
    with st.container(key="japanese_learn_box"):
        render_learn(deck)
    # The same for Review, which changes size with every card: the kana
    # drill below it would otherwise take the focus after each answer.
    with st.container(key="japanese_review_box"):
        render_review(deck)
    # Public version only: the author's own copy has no use for it.
    if not PRIVATE_LOOK:
        render_kana(deck)
    render_add_cards(deck)
    render_your_cards(deck)
    render_resources()
