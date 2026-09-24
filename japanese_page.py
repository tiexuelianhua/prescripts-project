# Japanese page: flashcards for vocab and kanji the user already knows,
# reviewed on a spaced-repetition (SRS) schedule -- either revealed and
# self-graded, or typed and checked (realkana-style) -- plus a lookup of the
# whole deck. New cards can be filled in from Jisho / kanjiapi.dev. Grammar
# is planned for later. All data/scheduling lives in japanese_data.py (no UI
# there), so the Overview tile can read it too.
import html
import urllib.error

import pandas as pd
import streamlit as st

from japanese_data import (
    GRADE_LABELS,
    GRADES,
    KIND_LABELS,
    KINDS,
    add_card,
    answer_prompt,
    check_answer,
    delete_cards,
    due_cards,
    find_duplicate,
    format_interval,
    jisho_lookup,
    kanji_lookup,
    load_deck,
    next_schedule,
    regrade,
    review_card,
    save_deck,
    search_cards,
    today_jst,
    update_card,
)
from prescripts_common import LOGO_PATH, inject_body_fade_in, render_page_title, theme_colors, typewriter

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


def render_flashcard(card: dict, show_back: bool) -> None:
    back = ""
    if show_back:
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


deck = load_deck()

with st.container(key="main_body"):
    # Review: the page's primary content, so always visible (house style --
    # secondary sections go in expanders below).
    st.subheader("Review")
    filter_column, typed_column = st.columns([3, 2], vertical_alignment="bottom")
    with filter_column:
        review_filter = st.segmented_control(
            "Deck", list(DECK_FILTERS), default="All", required=True, key="japanese_review_filter"
        )
    with typed_column:
        # realkana-style: type the answer and have it checked, instead of
        # revealing it and grading yourself. Saved with the deck, so it
        # stays how it was left.
        typed_mode = st.toggle(
            "Type answers",
            value=deck["settings"].get("typed_answers", False),
            key="japanese_typed_toggle",
            help="Type the reading (vocab) or the meaning (kanji) and it's checked for you. Romaji turns into kana.",
        )
    if typed_mode != deck["settings"].get("typed_answers", False):
        deck["settings"]["typed_answers"] = typed_mode
        save_deck(deck)

    due = due_cards(deck, DECK_FILTERS[review_filter])
    reviewed_today = deck["reviews"].get(today_jst().isoformat(), 0)
    st.caption(f"{len(due)} due · {reviewed_today} reviewed today")

    # Typed mode moves straight on to the next card after an answer, so the
    # verdict on the one just answered shows here, above it.
    last_result = st.session_state.get("japanese_last_result")
    if typed_mode and last_result:
        answered = last_result["card"]
        answer = " · ".join(part for part in (answered["reading"], answered["meaning"]) if part)
        verdict_column, override_column = st.columns([4, 1], vertical_alignment="center")
        with verdict_column:
            if last_result["correct"]:
                st.markdown(f"✅ **{html.escape(answered['front'])}** — {html.escape(answer)}")
            else:
                typed_note = f" (you typed *{html.escape(last_result['typed'])}*)" if last_result["typed"] else ""
                st.markdown(f"❌ **{html.escape(answered['front'])}** — {html.escape(answer)}{typed_note}")
        if not last_result["correct"] and last_result["typed"]:
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
    elif not due:
        upcoming = sorted(
            card["due"] for card in deck["cards"] if card["kind"] in DECK_FILTERS[review_filter]
        )
        if upcoming:
            st.write(f"Nothing due right now. Next card is due {upcoming[0]}.")
        else:
            st.write(f"No {review_filter.lower()} cards yet.")
    elif typed_mode:
        card = due[0]
        render_flashcard(card, show_back=False)
        asks_reading = answer_prompt(card) == "reading"
        with st.form("japanese_typed_form", clear_on_submit=True, border=False):
            typed = st.text_input(
                "Reading (kana or romaji)" if asks_reading else "Meaning",
                key="japanese_typed_answer",
                placeholder="Leave blank and press Enter if you don't know it",
            )
            checked = st.form_submit_button("Check", width="stretch")
        if checked:
            correct = bool(typed.strip()) and check_answer(card, typed)
            snapshot = dict(card)
            review_card(deck, card["id"], "good" if correct else "again")
            save_deck(deck)
            st.session_state["japanese_last_result"] = {"card": snapshot, "correct": correct, "typed": typed.strip()}
            st.rerun()
        # Puts the cursor back in the answer box for each new card, so a
        # review session is just type, Enter, type, Enter. The card id and
        # count make the snippet differ per card -- an unchanged one isn't
        # re-run.
        st.html(
            f"<script>/* {card['id']} {reviewed_today} */"
            "setTimeout(() => document.querySelector('.st-key-japanese_typed_answer input')?.focus(), 100);"
            "</script>",
            unsafe_allow_javascript=True,
        )
    else:
        card = due[0]
        # Which card's answer is showing -- by id, so answering (or the
        # queue changing under it) hides the answer for whatever comes next.
        revealed = st.session_state.get("japanese_revealed") == card["id"]
        render_flashcard(card, show_back=revealed)

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
        add_kind = st.segmented_control(
            "Type", KINDS, format_func=KIND_LABELS.get, default="vocab", required=True, key="japanese_add_kind"
        )
        # Cleared here, before the fields exist, after a card is added --
        # a widget's value can't be changed once it's been drawn this run.
        if st.session_state.pop("_reset_japanese_add", False):
            for key in ("japanese_add_lookup", "japanese_add_front", "japanese_add_reading", "japanese_add_meaning"):
                st.session_state[key] = ""
            st.session_state.pop("_japanese_filled_from", None)

        is_vocab = add_kind == "vocab"
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
                st.session_state["_japanese_filled_from"] = filled_from

        front = st.text_input("Word" if is_vocab else "Kanji", key="japanese_add_front")
        reading = st.text_input("Reading (hiragana)", key="japanese_add_reading") if is_vocab else ""
        meaning = st.text_input("Meaning", key="japanese_add_meaning")
        if st.button("Add card", key="japanese_add_button"):
            if not front.strip() or not meaning.strip():
                st.toast(f"A card needs both the {'word' if is_vocab else 'kanji'} and its meaning.", icon="⚠️")
            elif find_duplicate(deck, add_kind, front):
                st.toast(f"{front.strip()} is already in your {KIND_LABELS[add_kind].lower()} cards.", icon="⚠️")
            else:
                card = add_card(deck, add_kind, front, reading, meaning)
                save_deck(deck)
                st.session_state["_reset_japanese_add"] = True
                # Typed out under the button on the next run, like Meal
                # Receipts' "[Logged ...]" line -- stashed rather than typed
                # here, since st.rerun() below would discard it unseen.
                reading_note = f" ({card['reading']})" if card["reading"] else ""
                st.session_state["_japanese_add_confirmation"] = (
                    f"[Added {card['front']}{reading_note}: {card['meaning']}]"
                )
                st.rerun()
        else:
            # Popped so it types out once, not on every later rerun.
            pending_confirmation = st.session_state.pop("_japanese_add_confirmation", None)
            if pending_confirmation:
                typewriter(pending_confirmation)

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
            st.caption("Changes save as you make them. Select rows and press Delete to remove cards.")
            # Same as Meal Receipts' Entries: saved as soon as anything in
            # the table changes, no Save button.
            editor_changes = st.session_state.get(editor_key, {})
            if any(editor_changes.get(part) for part in ("edited_rows", "deleted_rows")):
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
