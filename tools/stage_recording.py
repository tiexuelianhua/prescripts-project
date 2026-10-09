"""Set up a made-up-data copy of the app for recording the demo video.

Run from the repo folder:

    .venv\\Scripts\\python tools\\stage_recording.py           # set it up
    .venv\\Scripts\\python tools\\stage_recording.py --serve   # ...and start it on port 8601
    .venv\\Scripts\\python tools\\stage_recording.py --remove  # delete it afterwards

Like take_screenshots.py, it never touches real data: the code is copied to
C:\\Prescripts\\prescripts-project (a neutral path, since Budget shows its
folder) and filled with the README screenshots' sample data, plus what each
shot of the recording needs -- a few months of spending for Month by month,
past fares so From/To fills in a price, konbini bags, grammar points on 静か,
trouble cards, cards in Learn and a drawn mnemonic. Dates count back from
the day it's run, so set it up on the day of recording (or the day before).
Unlike take_screenshots.py, the copy stays until --remove.
"""
import argparse
import random
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from take_screenshots import STAGE_ROOT, copy_code, server_is_up  # noqa: E402

COPY = STAGE_ROOT / "prescripts-project"


def seed_recording_data(copy: Path) -> None:
    # On top of take_screenshots' sample data, in its own process inside the
    # copy, so the app's own functions write the copy's data folders.
    sys.path.insert(0, str(copy))
    import prescripts.common as prescripts_common

    assert prescripts_common.SCRIPTS_DIR == copy, "not running on the copy"
    assert not prescripts_common.PRIVATE_LOOK, "the copy should be in the public look"

    from prescripts.data.japanese.deck import add_card, load_deck, review_card, save_deck, save_drawing, today_jst
    from prescripts.data.japanese.grammar import add_starter_points
    from prescripts.data.meal_receipts import BAG_ITEM, TRANSIT_FEE_ITEM, append_entry, day_folder_for

    random.seed(13)
    today = today_jst()

    def log(day: date, time: str, store: str | None, item: str, cost: int, category: str = "Food") -> None:
        folder = day_folder_for(day)
        folder.mkdir(parents=True, exist_ok=True)
        append_entry(folder / "receipts.csv", f"{day} {time}", store, item, cost, category=category)

    # Three months before this one, so Month by month has a history.
    meals = [("Lawson", "Onigiri (salmon)", 160), ("FamilyMart", "Famichiki", 220), ("Matsuya", "Gyūmeshi", 460),
             ("Sukiya", "Cheese gyūdon", 590), ("7-Eleven", "Egg sandwich", 298), ("Hanamaru Udon", "Kake udon", 390)]
    first_of_month = today.replace(day=1)
    day = first_of_month
    for _ in range(3):
        day = (day - timedelta(days=1)).replace(day=1)
    while day < first_of_month:
        for hour in sorted(random.sample([8, 12, 13, 18, 19], k=2)):
            store, item, cost = random.choice(meals)
            log(day, f"{hour:02d}:{random.randint(0, 59):02d}:00", store, item, cost)
        if day.weekday() == 0:
            log(day, "07:50:00", "Shinjuku", "Suica top-up", 3000, "Transport")
        if day.day in (9, 23):
            log(day, "16:30:00", random.choice(["Uniqlo", "Don Quijote", "Animate"]),
                random.choice(["Hoodie", "Phone case", "Keychain"]), random.choice([1990, 1280, 880]), "Shopping")
        day += timedelta(days=1)

    # Fares between two stations, both ways, so picking them fills in the
    # price; and konbini bags, so the bag's price fills in too.
    for days_ago, route in ((2, "Shinjuku → Shibuya"), (6, "Shibuya → Shinjuku"), (9, "Shinjuku → Akihabara")):
        if days_ago < today.day:
            fare = 170 if "Akihabara" not in route else 200
            log(today - timedelta(days=days_ago), "09:10:00", route, TRANSIT_FEE_ITEM, fare, "Transport")
    for days_ago, store in ((1, "Lawson"), (4, "FamilyMart"), (5, "7-Eleven")):
        if days_ago < today.day:
            log(today - timedelta(days=days_ago), "12:40:00", store, BAG_ITEM, 5)

    # Japanese: words the starter grammar fits (静か + じゃなかった), a couple
    # of trouble cards, and cards in Learn, one with a drawing.
    deck = load_deck()
    for front, reading, meaning, pos in [
        ("静か", "しずか", "quiet", "Na-adjective"), ("元気", "げんき", "healthy, energetic", "Na-adjective, Noun"),
        ("学生", "がくせい", "student", "Noun"), ("食べる", "たべる", "to eat", "Ichidan verb"),
    ]:
        add_card(deck, "vocab", front, reading, meaning, pos=pos)
    add_starter_points(deck)
    for front in ("約束", "忘れる"):
        card = next(card for card in deck["cards"] if card["front"] == front)
        for grade in ("good", "again", "good", "again"):
            review_card(deck, card["id"], grade)
        card["due"] = today.isoformat()
    for front, reading, meaning, pos in [("駅", "えき", "station", "Noun"), ("会社", "かいしゃ", "company", "Noun")]:
        add_card(deck, "vocab", front, reading, meaning, pos=pos, learning=True)
    forest = add_card(deck, "kanji", "森", "", "forest", onyomi="シン", kunyomi="もり", learning=True,
                      note="Three trees make a forest")
    # Some reviews on earlier days too, for the Overview tile's count.
    deck["reviews"][(today - timedelta(days=1)).isoformat()] = 12
    save_deck(deck)
    save_drawing(forest["id"], _three_trees())


def _three_trees() -> bytes:
    # A drawn mnemonic for 森: three little trees, in the public look's
    # accent colour on a clear 640px square, like the drawing box saves.
    from io import BytesIO

    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (640, 640), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    ink = (117, 120, 178, 255)
    for x, y, size in ((320, 150, 120), (170, 380, 120), (470, 380, 120)):
        pen.polygon([(x, y - size), (x - size * 0.8, y + size * 0.6), (x + size * 0.8, y + size * 0.6)],
                    outline=ink, width=10)
        pen.line([(x, y + size * 0.6), (x, y + size * 1.1)], fill=ink, width=12)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--serve", action="store_true", help="start the copy on --port once it's set up")
    parser.add_argument("--port", type=int, default=8601, help="port for the copy (not the app's 8501)")
    parser.add_argument("--remove", action="store_true", help=f"delete {STAGE_ROOT} and stop")
    parser.add_argument("--seed-into", type=Path, help=argparse.SUPPRESS)  # internal: see seed_recording_data
    args = parser.parse_args()

    if args.seed_into:
        seed_recording_data(args.seed_into)
        return
    if args.remove:
        shutil.rmtree(STAGE_ROOT, ignore_errors=True)
        print(f"{STAGE_ROOT} removed." if not STAGE_ROOT.exists() else f"Couldn't remove all of {STAGE_ROOT}: "
              "is the copy still running?")
        return
    if STAGE_ROOT.exists():
        raise SystemExit(f"{STAGE_ROOT} already exists. Run with --remove first to start over.")

    print(f"Copying the code to {COPY} ...")
    copy_code(COPY)
    print("Filling it with made-up data ...")
    tools = Path(__file__).resolve().parent
    for script in (tools / "take_screenshots.py", Path(__file__).resolve()):
        seeded = subprocess.run([sys.executable, str(script), "--seed-into", str(COPY)], cwd=COPY,
                                capture_output=True, text=True, encoding="utf-8")
        if seeded.returncode:
            raise SystemExit(f"Filling in data failed ({script.name}):\n{seeded.stderr}")
    print(f"Ready in {COPY}.")
    if args.serve:
        if server_is_up(args.port):
            raise SystemExit(f"Something is already serving on port {args.port} -- pick another with --port.")
        print(f"Serving it on http://127.0.0.1:{args.port} (Ctrl+C to stop) ...")
        subprocess.run([sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(args.port),
                        "--server.headless", "true"], cwd=COPY)


if __name__ == "__main__":
    main()
