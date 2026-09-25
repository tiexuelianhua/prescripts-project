# Data for the Home page: quotes added by the user, which join the built-in
# ones (home_page.BUILT_IN_QUOTES) in the rotating prompt and are credited in
# the corner whenever one of them is showing. No Streamlit rendering here
# (same data/page split as the other pages). Kept outside the repo like every
# page's data.
import html
import json
import re
import urllib.parse

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


# Words around a request that aren't what's being asked for: "go to meal
# receipts please" is about "meal receipts". Longest phrases first, so "take
# me to" is stripped whole rather than just its "to".
_COMMAND_PHRASES = sorted([
    "go to", "goto", "open", "open up", "show", "show me", "take me to", "bring up", "switch to",
    "navigate to", "launch", "i want to", "i'd like to", "let's", "lets", "can you", "could you",
    "please", "the", "my", "page", "tab",
], key=len, reverse=True)
_COMMAND_PATTERN = re.compile(r"\b(?:" + "|".join(re.escape(p) for p in _COMMAND_PHRASES) + r")\b")
_JAPANESE_TEXT = re.compile(r"[぀-ヿ㐀-鿿]")


def route_command(query: str, pages: list[dict]) -> dict:
    # What Home's box should do with what was typed:
    #   {"action": "page", "page": ...}          -- exactly one page fits
    #   {"action": "choose", "pages": [...]}     -- more than one fits
    #   {"action": "search", "links": [(label, url), ...]}  -- no page fits
    # A page fits when its title or one of its keywords appears in the
    # request as whole words ("what's the weather like" -> Weather), or when
    # what's left is the start of one (typing "wea" still finds Weather).
    text = query.strip().lower()
    subject = " ".join(_COMMAND_PATTERN.sub(" ", text).split())
    matches = []
    for page in pages:
        names = [page["title"].lower(), *page["keywords"]]
        for name in names:
            if _JAPANESE_TEXT.search(name):
                found = name in text  # no word boundaries in Japanese
            else:
                found = re.search(r"\b" + re.escape(name) + r"\b", text) is not None
            if found or (len(subject) >= 3 and name.startswith(subject)):
                matches.append(page)
                break
    if len(matches) == 1:
        return {"action": "page", "page": matches[0]}
    if matches:
        return {"action": "choose", "pages": matches}
    search_for = query.strip()
    links = [("Search Google for it", "https://www.google.com/search?q=" + urllib.parse.quote_plus(search_for))]
    if _JAPANESE_TEXT.search(search_for):
        links.insert(0, ("Look it up on Jisho", "https://jisho.org/search/" + urllib.parse.quote(search_for)))
    return {"action": "search", "links": links}


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
