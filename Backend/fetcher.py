# Playwright lifecycle helpers.
# The sync API owns one asyncio loop per instance, so every connector job
# runs its own short-lived (headful) Chromium inside its own thread - stores
# are then searched in parallel. Storage state (cookies) per store is kept
# in profiles/<store>.json so a one-time setup persists across searches.

import threading
from pathlib import Path

PROFILE_DIR = Path(__file__).resolve().parent / "profiles"
PROFILE_DIR.mkdir(exist_ok=True)

STEALTH = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = { runtime: {} };
"""

MOBILE_UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 8) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36")

STORE_SETTINGS = {
    "zepto": {"user_agent": MOBILE_UA, "viewport": {"width": 390, "height": 780},
              "locale": "en-IN", "timezone_id": "Asia/Kolkata"},
    "instamart": {"user_agent": MOBILE_UA, "viewport": {"width": 390, "height": 780},
                  "locale": "en-IN", "timezone_id": "Asia/Kolkata",
                  "geolocation": {"latitude": 19.076, "longitude": 72.8777},
                  "permissions": ["geolocation"]},
    "blinkit": {"user_agent": MOBILE_UA, "viewport": {"width": 390, "height": 780},
                "locale": "en-IN", "timezone_id": "Asia/Kolkata",
                "geolocation": {"latitude": 19.076, "longitude": 72.8777},
                "permissions": ["geolocation"]},
    "bigbasket": {"viewport": {"width": 1280, "height": 820},
                  "locale": "en-IN", "timezone_id": "Asia/Kolkata"},
}


def browser_job(store: str, fn, timeout: float = 110):
    """Run fn(page) -> payload for `store` in its own headful Chromium."""
    done = threading.Event()
    box: dict = {}

    def runner():
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as p:
                args = ["--window-position=60,30",
                        "--disable-blink-features=AutomationControlled",
                        "--no-first-run", "--no-default-browser-check"]
                try:  # real Chrome passes bot-checks much better than the bundled build
                    browser = p.chromium.launch(channel="chrome", headless=False, args=args)
                except Exception:
                    browser = p.chromium.launch(headless=False, args=args)
                settings = dict(STORE_SETTINGS.get(store, {}))
                profile = PROFILE_DIR / f"{store}.json"
                if profile.exists():
                    settings["storage_state"] = str(profile)
                ctx = browser.new_context(**settings)
                ctx.add_init_script(STEALTH)
                page = ctx.new_page()
                try:
                    box["result"] = fn(page)
                except Exception as e:      # noqa: BLE001
                    box["error"] = e
                try:    # persist cookies so a one-time setup is reused
                    ctx.storage_state(path=str(profile))
                except Exception:
                    pass
                browser.close()
        except Exception as e:              # noqa: BLE001
            box.setdefault("error", e)
        done.set()

    threading.Thread(target=runner, daemon=True).start()
    if not done.wait(timeout):
        raise TimeoutError(f"{store} did not finish within {timeout:.0f}s")
    if "error" in box:
        raise box["error"]
    return box["result"]
