# Data for the Home page: quotes added by the user, which join the built-in
# ones (home_page.BUILT_IN_QUOTES) in the rotating prompt and are credited in
# the corner whenever one of them is showing. No Streamlit rendering here
# (same data/page split as the other pages). Kept outside the repo like every
# page's data.
import html
import json

from prescripts_common import SCRIPTS_DIR

QUOTES_PATH = SCRIPTS_DIR.parent / "quotes.json"


def load_quotes() -> list[dict]:
    # Each quote: {"line", "source", "by", "note"} -- only "line" is required.
    try:
        with open(QUOTES_PATH, encoding="utf-8") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def save_quotes(quotes: list[dict]) -> None:
    with open(QUOTES_PATH, "w", encoding="utf-8") as file:
        json.dump(quotes, file, ensure_ascii=False, indent=2)


def add_quote(line: str, source: str = "", by: str = "", note: str = "") -> None:
    quotes = load_quotes()
    quotes.append({"line": line.strip(), "source": source.strip(), "by": by.strip(), "note": note.strip()})
    save_quotes(quotes)


def remove_quote(index: int) -> None:
    quotes = load_quotes()
    if 0 <= index < len(quotes):
        del quotes[index]
        save_quotes(quotes)


def quote_credit(quote: dict, escape: bool = True) -> str:
    # One line naming where the quote comes from, e.g.
    #   This line is from "Hero" by Mili.
    # Empty when there's nothing to credit (no source and no author given).
    # Goes into HTML, so typed-in text is escaped (a "<" or "&" would
    # otherwise be read as markup); only the built-in quotes, whose notes use
    # markup on purpose, pass escape=False.
    source, by, note = (quote.get(key, "") for key in ("source", "by", "note"))
    if escape:
        source, by, note = html.escape(source), html.escape(by), html.escape(note)
    if not (source or by):
        return ""
    credit = "This line is from " + (f'"{source}"' if source else "a work")
    credit += f" by {by}" if by else ""
    credit += f" ({note})" if note else ""
    return credit + "."
