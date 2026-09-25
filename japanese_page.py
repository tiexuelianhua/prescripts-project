# Japanese page: flashcards for vocab and kanji the user already knows,
# reviewed on a spaced-repetition (SRS) schedule -- either revealed and
# self-graded, or typed and checked (realkana-style) -- plus a lookup of the
# whole deck. New cards can be filled in from Jisho / kanjiapi.dev. Grammar
# is planned for later. All data/scheduling lives in japanese_data.py (no UI
# there), so the Overview tile can read it too.
import html
import random
import urllib.error
import uuid

import pandas as pd
import streamlit as st

from japanese_data import (
    GRADE_LABELS,
    GRADES,
    KIND_LABELS,
    KINDS,
    STEP_LABELS,
    add_card,
    answer_steps,
    check_new_card,
    check_step,
    delete_cards,
    display_readings,
    due_cards,
    find_duplicate,
    format_interval,
    has_distinct_reading,
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
from prescripts_common import inject_body_fade_in, render_page_title, show_logo, theme_colors, typewriter

TEXT_COLOR, ACCENT_COLOR = theme_colors()
PAGE_TITLE = "Japanese"
# Choices for the deck filters (review and lookup): both kinds, or just one.
DECK_FILTERS = {"All": KINDS, "Vocab": ["vocab"], "Kanji": ["kanji"]}

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
    .flashcard-kanji-reading {{
        margin-top: 0.4rem;
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


def render_flashcard(card: dict, show_back: bool) -> None:
    back = ""
    if show_back:
        if has_distinct_reading(card):
            back += f'<div class="flashcard-reading">{html.escape(card["reading"])}</div>'
        back += f'<div class="flashcard-meaning">{html.escape(card["meaning"])}</div>'
        # Kanji: meaning first, then each kind of reading -- the order typed
        # mode asks for them in.
        for field, label in (("onyomi", "On"), ("kunyomi", "Kun")):
            if card.get(field):
                readings = html.escape(display_readings(card[field]))
                back += f'<div class="flashcard-kanji-reading" lang="ja"><span>{label}</span>{readings}</div>'
    st.markdown(
        f'<div class="flashcard">'
        f'<div class="flashcard-kind">{KIND_LABELS[card["kind"]]}</div>'
        f'<div class="flashcard-front" lang="ja">{html.escape(card["front"])}</div>'
        f"{back}</div>",
        unsafe_allow_html=True,
    )


def answer_summary(card: dict) -> str:
    # The whole back of a card on one line, for the typed-mode verdict.
    parts = [card["reading"] if has_distinct_reading(card) else "", card["meaning"]]
    if card.get("onyomi"):
        parts.append(f"on {display_readings(card['onyomi'])}")
    if card.get("kunyomi"):
        parts.append(f"kun {display_readings(card['kunyomi'])}")
    return " · ".join(part for part in parts if part)


def step_answer(card: dict, step: str) -> str:
    # The right answer for one typed part, shown when it's missed.
    return display_readings(card[step]) if step in ("onyomi", "kunyomi") else card[step]


STEP_NAMES = {"reading": "Reading", "meaning": "Meaning", "onyomi": "On'yomi", "kunyomi": "Kun'yomi"}


ADD_FIELD_KEYS = {
    "front": "japanese_add_front",
    "reading": "japanese_add_reading",
    "onyomi": "japanese_add_onyomi",
    "kunyomi": "japanese_add_kunyomi",
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


def practice_card(deck: dict, kinds: list[str], filter_name: str) -> tuple[dict | None, int, int]:
    # Practice goes through the chosen deck in a shuffled order, then
    # reshuffles and goes round again, forever. Returns (card, its 1-based
    # place in this round, cards in the round). The order is rebuilt when
    # the deck filter changes or a card in it has been deleted.
    cards = {card["id"]: card for card in deck["cards"] if card["kind"] in kinds}
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


deck = load_deck()

with st.container(key="main_body"):
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
            help="Type the reading and meaning (plus on'yomi/kun'yomi for kanji) and they're checked for you. Romaji turns into kana.",
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
        card, position, total = practice_card(deck, kinds, review_filter)
        if card:
            st.caption(f"Practice · card {position} of {total} · doesn't change when cards are due")
    else:
        st.caption(f"{len(due)} due · {reviewed_today} reviewed today")
        if due:
            card = due[0]

    # Typed mode moves straight on to the next card after an answer, so the
    # verdict on the one just answered shows here, above it.
    # A card is typed in parts (vocab: reading, meaning; kanji: meaning,
    # on'yomi, kun'yomi); this is how far into the current card that's got.
    # The last card's verdict is hidden while one is part-way through, so the
    # marks shown are all for the card on screen.
    progress = st.session_state.get("japanese_step")
    if card is None or not progress or progress["key"] != (card["id"], practice_mode):
        progress = {"key": (card["id"], practice_mode) if card else None, "parts": []}
    last_result = st.session_state.get("japanese_last_result")
    if typed_mode and last_result and not progress["parts"]:
        answered = last_result["card"]
        # Results saved before multi-part answers existed have no "parts".
        parts = last_result.get("parts") or [{"step": None, "ok": last_result["correct"], "typed": last_result["typed"]}]
        verdict_column, override_column = st.columns([4, 1], vertical_alignment="center")
        with verdict_column:
            icon = "✅" if last_result["correct"] else "❌"
            summary = f"{icon} **{html.escape(answered['front'])}** — {html.escape(answer_summary(answered))}"
            if len(parts) == 1 and not last_result["correct"] and parts[0]["typed"]:
                summary += f" (you typed *{html.escape(parts[0]['typed'])}*)"
            st.markdown(summary)
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
        st.write(f"No {review_filter.lower()} cards yet.")
    elif card is None:
        upcoming = sorted(other["due"] for other in deck["cards"] if other["kind"] in kinds)
        if upcoming:
            st.write(f"Nothing due right now. Next card is due {upcoming[0]}.")
            st.caption("Turn on **Practice** to keep going anyway.")
        else:
            st.write(f"No {review_filter.lower()} cards yet.")
    elif typed_mode:
        render_flashcard(card, show_back=False)
        steps = answer_steps(card)
        if len(progress["parts"]) >= len(steps):  # card edited to fewer parts mid-way
            progress["parts"] = []
        step = steps[len(progress["parts"])]
        if len(steps) > 1:
            # Parts already answered for this card, each marked as it goes
            # (a miss shows the answer) -- a wrong part doesn't end the card,
            # every part still gets asked.
            done = [
                f"{STEP_NAMES[part['step']]} {'✅' if part['ok'] else '❌ ' + step_answer(card, part['step'])}"
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
            progress["parts"].append({"step": step, "ok": check_step(card, step, typed), "typed": typed.strip()})
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
        render_flashcard(card, show_back=revealed)

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
            ):
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
                st.session_state["japanese_add_onyomi"] = chosen.get("on", "")
                st.session_state["japanese_add_kunyomi"] = chosen.get("kun", "")
                st.session_state["_japanese_filled_from"] = filled_from

        front = st.text_input("Word" if is_vocab else "Kanji", key="japanese_add_front")
        reading = (
            st.text_input(
                "Reading (hiragana)",
                key="japanese_add_reading",
                help="Can be left blank for words written in kana -- they're quizzed on their meaning instead.",
            )
            if is_vocab
            else ""
        )
        meaning = st.text_input("Meaning", key="japanese_add_meaning")
        onyomi = kunyomi = ""
        if not is_vocab:
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
        }
        pending = st.session_state.get("_japanese_add_issues")
        if pending and pending["values"] != current_values:
            st.session_state.pop("_japanese_add_issues", None)
            pending = None

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
            if not front.strip() or not meaning.strip():
                st.toast(f"A card needs both the {'word' if is_vocab else 'kanji'} and its meaning.", icon="⚠️")
            elif find_duplicate(deck, add_kind, front):
                st.toast(f"{front.strip()} is already in your {KIND_LABELS[add_kind].lower()} cards.", icon="⚠️")
            else:
                issues = []
                if add_clicked:
                    # Checked against Jisho / KANJIDIC for typos first; if
                    # neither can be reached, the card's just added as usual.
                    try:
                        issues = check_new_card(add_kind, front, reading, onyomi, kunyomi)
                    except (urllib.error.URLError, TimeoutError, ValueError, KeyError):
                        issues = []
                if issues:
                    st.session_state["_japanese_add_issues"] = {"values": current_values, "issues": issues}
                    st.rerun()
                card = add_card(deck, add_kind, front, reading, meaning, onyomi, kunyomi)
                save_deck(deck)
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
                    f"[Added {card['front']}{reading_note}: {card['meaning']}{kanji_readings}]"
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
                        "onyomi": card["onyomi"],
                        "kunyomi": card["kunyomi"],
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
            # Room for the table's hover toolbar, which sits just above its
            # top-right corner -- otherwise right over the Deck buttons.
            st.space("small")
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
                    "onyomi": st.column_config.TextColumn("On'yomi", help="Kanji only"),
                    "kunyomi": st.column_config.TextColumn("Kun'yomi", help="Kanji only"),
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
                        onyomi=row["onyomi"] if kind == "kanji" else "",
                        kunyomi=row["kunyomi"] if kind == "kanji" else "",
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
