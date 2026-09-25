"""Retake the README screenshots (docs/screenshots/) of the public look.

Run from the repo folder, with the app closed or not -- it doesn't matter:

    .venv\\Scripts\\python tools\\take_screenshots.py

It never touches real data. It copies the code to C:\\Prescripts\\prescripts-project,
fills that copy with made-up meals and flashcards, serves it on its own port,
screenshots each page in a headless Chrome (or Edge), and deletes
C:\\Prescripts again. C:\\Prescripts is used, rather than somewhere under your
user folder, because the Meal Receipts page shows its full folder path -- a
temp folder would put your Windows username in the screenshot.

Look at every image before committing: the Home prompt is picked at random,
and Weather shows that day's real forecast.
"""
import argparse
import asyncio
import base64
import json
import random
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import timedelta
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent
STAGE_ROOT = Path(r"C:\Prescripts")
WIDTH = 1280

# (file name, page's url path, element that means it's loaded, height to capture)
SHOTS = [
    ("home", "", "details summary", 800),
    ("overview", "overview_page", "[data-testid^=stBaseButton]", 1100),
    ("meal_receipts", "mealReceiptsApp_cV", ".st-key-add_entry_item input", 1500),
    ("japanese", "japanese_page", "[data-testid^=stBaseButton]", 1060),
    ("weather", "weather_page", "[data-testid^=stBaseButton], [data-testid=stMetric]", 1000),
]

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]


def seed_sample_data(copy: Path) -> None:
    # Runs in its own process (see main), inside the copy -- so the app's own
    # data functions write the copy's data folders, in exactly the format
    # the app itself writes.
    sys.path.insert(0, str(copy))
    import prescripts_common

    assert prescripts_common.SCRIPTS_DIR == copy, "not running on the copy"
    assert not prescripts_common.PRIVATE_LOOK, "the copy should be in the public look"

    from japanese_data import add_card, load_deck, review_card, save_deck, today_jst
    from meal_receipts_data import append_entry, day_folder_for, load_settings, save_settings

    random.seed(7)
    today = today_jst()

    # This month so far: two or three meals a day, one entry left out of totals.
    meals = [
        ("Lawson", "Onigiri (salmon)", 160), ("Lawson", "Karaage-kun", 238),
        ("FamilyMart", "Famichiki", 220), ("FamilyMart", "Iced coffee", 130),
        ("7-Eleven", "Egg sandwich", 298), ("7-Eleven", "Oden set", 380),
        ("Matsuya", "Gyūmeshi", 460), ("Sukiya", "Cheese gyūdon", 590),
        ("Coco Ichibanya", "Pork curry", 780), ("Hanamaru Udon", "Kake udon", 390),
    ]
    for days_ago in range(today.day - 1, -1, -1):
        day = today - timedelta(days=days_ago)
        folder = day_folder_for(day)
        folder.mkdir(parents=True, exist_ok=True)
        for hour in sorted(random.sample([8, 12, 13, 18, 19, 21], k=random.choice([2, 3]))):
            store, item, cost = random.choice(meals)
            append_entry(folder / "receipts.csv", f"{day} {hour:02d}:{random.randint(0, 59):02d}:00", store, item, cost)
        if days_ago == 3:
            append_entry(folder / "receipts.csv", f"{day} 20:15:00", "Izakaya", "Team dinner", 3500,
                         excluded=True, excluded_reason="Covered by friend/coworker")
    settings = load_settings()
    settings.update({"budget_amount": 7000, "budget_period": "weekly"})
    save_settings(settings)

    # A small deck, a few cards already reviewed today.
    deck = load_deck()
    for front, reading, meaning in [
        ("勉強", "べんきょう", "study"), ("天気", "てんき", "weather"), ("電車", "でんしゃ", "train"),
        ("忘れる", "わすれる", "to forget"), ("美味しい", "おいしい", "delicious"), ("約束", "やくそく", "promise"),
    ]:
        add_card(deck, "vocab", front, reading=reading, meaning=meaning)
    for front, onyomi, kunyomi, meaning in [
        ("花", "カ", "はな", "flower"), ("雨", "ウ", "あめ", "rain"), ("食", "ショク", "た.べる", "eat, food"),
    ]:
        add_card(deck, "kanji", front, reading="", meaning=meaning, onyomi=onyomi, kunyomi=kunyomi)
    for card in deck["cards"][:4]:
        review_card(deck, card["id"], "good")
    save_deck(deck)


def copy_code(copy: Path) -> None:
    # Tracked files plus new ones not yet committed (but not ignored ones like
    # .venv), so the screenshots show the code as it is right now.
    files = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=REPO_DIR, capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout.splitlines()
    for name in files:
        source = REPO_DIR / name
        if source.is_file():
            target = copy / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def wait_until(check, timeout_s: float, what: str) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if check():
            return
        time.sleep(0.5)
    raise SystemExit(f"Timed out waiting for {what}.")


def server_is_up(port: int) -> bool:
    try:
        return urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=2).read() == b"ok"
    except OSError:
        return False


async def take_shots(app_port: int, cdp_port: int, out_dir: Path) -> list[Path]:
    import websockets

    targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json"))
    page = next(t for t in targets if t["type"] == "page")
    saved = []
    async with websockets.connect(page["webSocketDebuggerUrl"], max_size=None) as ws:
        message_id = 0

        async def send(method, params=None):
            nonlocal message_id
            message_id += 1
            await ws.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
            while True:
                reply = json.loads(await ws.recv())
                if reply.get("id") == message_id:
                    return reply.get("result", {})

        async def js(expression):
            result = await send("Runtime.evaluate", {"expression": expression, "returnByValue": True})
            return result.get("result", {}).get("value")

        await send("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": "dark"}]})
        for name, path, ready, height in SHOTS:
            await send("Emulation.setDeviceMetricsOverride",
                       {"width": WIDTH, "height": height, "deviceScaleFactor": 1, "mobile": False})
            await send("Page.navigate", {"url": f"http://127.0.0.1:{app_port}/{path}"})
            for _ in range(120):
                if await js(f"!!document.querySelector({json.dumps(ready)}) && "
                            "document.querySelector('[data-testid=stApp]').dataset.testScriptState !== 'running'"):
                    break
                await asyncio.sleep(0.5)
            await asyncio.sleep(4)  # page titles type themselves in, then content fades in
            if name == "japanese":
                await js("[...document.querySelectorAll('button')].find(b => b.innerText.trim() === 'Show answer')?.click()")
                await asyncio.sleep(3)
            await js("document.activeElement && document.activeElement.blur()")
            png = base64.b64decode((await send("Page.captureScreenshot", {"format": "png"}))["data"])
            target = out_dir / f"{name}.png"
            target.write_bytes(png)
            saved.append(target)
            print(f"  {name}.png")
    return saved


def stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    if sys.platform == "win32":
        # /T: the venv's python.exe starts the real interpreter as a child.
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
    else:
        process.terminate()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPO_DIR / "docs" / "screenshots", help="where the PNGs go")
    parser.add_argument("--port", type=int, default=8601, help="port for the copy's server (not the app's 8501)")
    parser.add_argument("--browser", help="path to chrome.exe or msedge.exe, if not in the usual place")
    parser.add_argument("--seed-into", type=Path, help=argparse.SUPPRESS)  # internal: see seed_sample_data
    args = parser.parse_args()

    if args.seed_into:
        seed_sample_data(args.seed_into)
        return

    browser = args.browser or next((path for path in BROWSERS if Path(path).exists()), None)
    if not browser:
        raise SystemExit("No Chrome or Edge found -- pass its path with --browser.")
    if STAGE_ROOT.exists():
        raise SystemExit(f"{STAGE_ROOT} already exists. It's used as a scratch folder here and deleted "
                         "afterwards, so move anything in it elsewhere first.")
    if server_is_up(args.port):
        raise SystemExit(f"Something is already serving on port {args.port} -- pick another with --port.")

    copy = STAGE_ROOT / "prescripts-project"
    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    server = browser_process = None
    try:
        print(f"Copying the code to {copy} ...")
        copy_code(copy)
        print("Filling it with sample data ...")
        seeded = subprocess.run([sys.executable, __file__, "--seed-into", str(copy)], cwd=copy,
                                capture_output=True, text=True, encoding="utf-8")
        if seeded.returncode:
            raise SystemExit(f"Filling in sample data failed:\n{seeded.stderr}")
        print(f"Starting it on port {args.port} ...")
        server = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(args.port),
             "--server.headless", "true"],
            cwd=copy, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        wait_until(lambda: server_is_up(args.port), 60, "the app to start")

        cdp_port = args.port + 1000
        browser_process = subprocess.Popen(
            [browser, "--headless=new", "--hide-scrollbars", f"--remote-debugging-port={cdp_port}",
             f"--user-data-dir={STAGE_ROOT / 'browser-profile'}", f"--window-size={WIDTH},800", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        wait_until(lambda: _cdp_is_up(cdp_port), 30, "the browser to start")

        print(f"Taking screenshots into {out_dir} ...")
        saved = asyncio.run(take_shots(args.port, cdp_port, out_dir))
        _compress(saved)
    finally:
        stop(browser_process)
        stop(server)
        for _ in range(20):  # the browser can hold its profile folder for a moment after exiting
            shutil.rmtree(STAGE_ROOT, ignore_errors=True)
            if not STAGE_ROOT.exists():
                break
            time.sleep(0.5)
    print(f"Done, and {STAGE_ROOT} removed. Look at every image before committing them.")


def _cdp_is_up(port: int) -> bool:
    try:
        return any(t["type"] == "page" for t in json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json")))
    except OSError:
        return False


def _compress(paths: list[Path]) -> None:
    from PIL import Image

    for path in paths:
        Image.open(path).convert("RGB").save(path, optimize=True)


if __name__ == "__main__":
    main()
