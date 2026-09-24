# Japanese page: flashcards for vocab and kanji the user already knows,
# reviewed on a spaced-repetition (SRS) schedule, plus a lookup of the whole
# deck. Grammar is planned for later. All data/scheduling lives in
# japanese_data.py (no UI there), so the Overview tile can read it too.
import html

import pandas as pd
import streamlit as st

from japanese_data import (
    GRADE_LABELS,
    GRADES,
    KIND_LABELS,
    KINDS,
    add_card,
    delete_cards,
    due_cards,
    find_duplicate,
    format_interval,
    load_deck,
    next_schedule,
    review_card,
    save_deck,
    search_cards,
    today_jst,
    update_card,
)
from prescripts_common import LOGO_PATH, inject_body_fade_in, render_page_title, theme_colors

TEXT_COLOR, ACCENT_COLOR = theme_colors()
PAGE_TITLE = "Japanese"
# Choices for the deck filters (review and lookup): both kinds, or just one.
DECK_FILTERS = {"All": KINDS, "Vocab": ["vocab"], "Kanji": ["kanji"]}

is_first_load = "_japanese_title_played" not in st.session_state
inject_body_fade_in("main_body")

header_logo, header_title = st.columns([1, 4], vertical_alignment="center")
with header_logo:
    st.image(str(LOGO_PATH), width=120)
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
    </style>
    """,
    unsafe_allow_html=True,
)

deck = load_deck()

with st.container(key="main_body"):
    # Review: the page's primary content, so always visible (house style --
    # secondary sections go in expanders below).
    st.subheader("Review")
    review_filter = st.segmented_control(
        "Deck", list(DECK_FILTERS), default="All", required=True, key="japanese_review_filter"
    )
    due = due_cards(deck, DECK_FILTERS[review_filter])
    reviewed_today = deck["reviews"].get(today_jst().isoformat(), 0)
    st.caption(f"{len(due)} due · {reviewed_today} reviewed today")

    if not deck["cards"]:
        st.write("No cards yet -- add some below.")
    elif not due:
        upcoming = sorted(
            card["due"] for card in deck["cards"] if card["kind"] in DECK_FILTERS[review_filter]
        )
        if upcoming:
            st.write(f"Nothing due right now. Next card is due {upcoming[0]}.")
        else:
            st.write(f"No {review_filter.lower()} cards yet.")
    else:
        card = due[0]
        # Which card's answer is showing -- by id, so answering (or the
        # queue changing under it) hides the answer for whatever comes next.
        revealed = st.session_state.get("japanese_revealed") == card["id"]
        back = ""
        if revealed:
            if card["kind"] == "vocab" and card["reading"]:
                back += f'<div class="flashcard-reading">{html.escape(card["reading"])}</div>'
            back += f'<div class="flashcard-meaning">{html.escape(card["meaning"])}</div>'
        st.markdown(
            f'<div class="flashcard">'
            f'<div class="flashcard-kind">{KIND_LABELS[card["kind"]]}</div>'
            f'<div class="flashcard-front" lang="ja">{html.escape(card["front"])}</div>'
            f"{back}</div>",
            unsafe_allow_html=True,
        )

        if not revealed:
            if st.button("Show answer", key="japanese_show_answer", width="stretch"):
                st.session_state["japanese_revealed"] = card["id"]
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

    # Adding cards: open by default only while the deck is still empty.
    with st.expander("Add cards", expanded=not deck["cards"]):
        # Outside the form so the fields below can change with it (a form
        # only reports widget values on submit).
        add_kind = st.segmented_control(
            "Type", KINDS, format_func=KIND_LABELS.get, default="vocab", required=True, key="japanese_add_kind"
        )
        with st.form("japanese_add_form", clear_on_submit=True, border=False):
            if add_kind == "vocab":
                front = st.text_input("Word", placeholder="e.g. 勉強")
                reading = st.text_input("Reading (hiragana)", placeholder="e.g. べんきょう")
            else:
                front = st.text_input("Kanji", placeholder="e.g. 学")
                reading = ""
            meaning = st.text_input("Meaning", placeholder="e.g. study")
            submitted = st.form_submit_button("Add card")
        if submitted:
            if not front.strip() or not meaning.strip():
                st.toast(f"A card needs both the {'word' if add_kind == 'vocab' else 'kanji'} and its meaning.", icon="⚠️")
            elif find_duplicate(deck, add_kind, front):
                st.toast(f"{front.strip()} is already in your {KIND_LABELS[add_kind].lower()} cards.", icon="⚠️")
            else:
                add_card(deck, add_kind, front, reading, meaning)
                save_deck(deck)
                # st.toast(), not st.success(): only a toast survives st.rerun().
                st.toast(f"Added {front.strip()}.", icon="✅")
                st.rerun()

    # Lookup of everything already in the deck, editable in place.
    with st.expander("Your cards"):
        search_columns = st.columns([3, 2], vertical_alignment="bottom")
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
            table = pd.DataFrame(
                [
                    {
                        "id": card["id"],
                        "kind": KIND_LABELS[card["kind"]],
                        "front": card["front"],
                        "reading": card["reading"],
                        "meaning": card["meaning"],
                        "due": card["due"],
                    }
                    for card in matches
                ]
            ).set_index("id")
            # Keyed by the filters too: a data_editor's pending edits are
            # tied to row positions, so a new search gets a fresh editor
            # instead of replaying edits onto whatever rows moved into place.
            editor_key = f"japanese_editor_{lookup_filter}_{query}"
            edited = st.data_editor(
                table,
                num_rows="delete",
                hide_index=True,
                width="stretch",
                key=editor_key,
                disabled=["kind", "due"],
                column_config={
                    "kind": "Type",
                    "front": "Word / kanji",
                    "reading": st.column_config.TextColumn("Reading", help="Vocab only"),
                    "meaning": "Meaning",
                    "due": "Next review",
                },
            )
            st.caption(f"{len(matches)} card(s)")
            # Same as Meal Receipts' Entries: nothing is written until Save,
            # so several cells can be edited before committing any of them.
            if st.button("💾 Save changes", key="japanese_save_cards"):
                deleted = set(table.index) - set(edited.index)
                delete_cards(deck, deleted)
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
                    )
                save_deck(deck)
                del st.session_state[editor_key]
                message = "Saved."
                if deleted:
                    message += f" Deleted {len(deleted)} card(s)."
                if clashes:
                    message += f" Skipped renaming to {', '.join(clashes)} (already in your cards)."
                st.toast(message)
                st.rerun()
            else:
                st.caption("Edits above aren't saved until you click **Save changes**. Select rows and press Delete to remove cards.")
