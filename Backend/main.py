import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import fetcher
import stores

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173",
                   "http://localhost:5174", "http://127.0.0.1:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)

CACHE_TTL = 600  # seconds
_cache: dict[str, tuple[float, dict]] = {}
# Scraping runs full Chromium instances; cap concurrency on small hosts
_pool = ThreadPoolExecutor(max_workers=int(os.environ.get("MAX_WORKERS", "4")))


class SearchResponse(BaseModel):
    query: str
    search_term: Optional[str] = None
    cheapest: Optional[dict] = None
    ai: Optional[dict] = None
    stores: list[dict]


@app.get("/health")
def health():
    return {"status": "ok"}


def _fresh_key(query: str) -> str:
    return " ".join(query.lower().split())


def _set_state(store: dict, profiles_dir=None) -> None:
    """Decorate a store result with whether a saved cookie profile exists."""
    profile = fetcher.PROFILE_DIR / f"{store['store']}.json"
    store["connected"] = profile.exists()


@app.get("/api/search", response_model=SearchResponse)
def search(q: str):
    from fastapi import HTTPException
    key = _fresh_key(q)
    if not key:
        raise HTTPException(400, "Type something to search.")
    hit = _cache.get(key)
    now = time.time()
    if hit and now - hit[0] < CACHE_TTL:
        cached = hit[1]
        return cached

    # ---- AGENT STEP 1: understand the query (doodh -> milk, etc.) ----------
    import llm_agent
    plan = llm_agent.plan(key)
    search_term = (plan or {}).get("search_term") or key

    def run(store):
        try:
            res = stores.search_store(store, search_term)
            status = res.get("status", "error")
            if status == "blocked":
                status = "needs_setup"
            res = {"status": status, "items": res.get("items", [])}
        except Exception as e:
            res = {"status": "error", "items": [], "error": str(e).splitlines()[0][:120]}
        return res

    futures = {s: _pool.submit(run, s) for s in stores.CONNECTORS}
    out_stores = []
    cheapest = None
    for s in stores.CONNECTORS:
        res = futures[s].result()     # per-run at most ~110s; run in parallel
        entry = {"store": s, "search_url": stores.SEARCH_URL[s] + urllib_quote(key),
                 **res}
        _set_state(entry)
        out_stores.append(entry)
        for it in res.get("items", []):
            if it.get("price") and (cheapest is None or it["price"] < cheapest["price"]):
                cheapest = {**it, "store": s}

    payload = {"query": key, "search_term": search_term, "cheapest": cheapest,
               "stores": sorted(out_stores,
                                key=lambda s: (s["status"] != "ok", s["store"]))}

    # ---- AGENT STEP 2: reason over the prices & write the verdict ----------
    verdict = llm_agent.analyze(key, payload["stores"])
    if verdict:
        import llm_agent as _la
        payload["ai"] = {
            "summary": _la.clean(verdict["summary"]),
            "winner": verdict.get("winner") or {},
            "per_store": verdict.get("per_store") or [],
            "search_reasoning": (plan or {}).get("reasoning", ""),
        }
        # if the agent found a fairer same-pack winner, surface that link too
        w = verdict.get("winner") or {}
        if w.get("name") and cheapest and w["name"] != cheapest.get("name"):
            payload["ai"]["cheapest_is_unfair"] = True

    _cache[key] = (now, payload)
    return payload


def urllib_quote(text: str) -> str:
    from urllib.parse import quote
    return quote(text)


@app.post("/api/chat")
def chat(body: dict):
    """Support chatbot: grounded on how THIS app works + the user's last search."""
    import llm_agent as _la
    from fastapi import HTTPException
    message = str(body.get("message") or "").strip()
    history = body.get("history") or []
    if not message:
        raise HTTPException(400, "Empty message")

    ctx = body.get("context") or {}
    store_states = ", ".join(
        f"{s['store']}: {s['status']} ({len(s.get('items', []))} items)"
        for s in ctx.get("stores", [])) or "no search yet"

    system = (
        "You are PricePeek's friendly support assistant. PricePeek is a local "
        "web app that compares product prices across Indian quick-commerce "
        "apps: Zepto, Swiggy Instamart and Blinkit (BigBasket was removed - "
        "their listing API blocks automated browsers). Facts you know:\n"
        "- Prices are live-scraped with a headful browser from MUMBAI pincode "
        "400001; delivery fees are not included.\n"
        "- A purple 'AI agent verdict' panel explains fair same-pack-size "
        "comparisons; the green banner is the plain lowest price.\n"
        "- Some stores show 'one-time connect needed': user clicks Connect "
        "store, a visible browser window opens, they complete the "
        "location/bot-check once, cookies are saved and the store turns live.\n"
        "- Stores can occasionally flicker to 'connect needed' when the site "
        "bot-checks us; clicking Compare again or reconnecting usually fixes "
        "it. Exact product links 'Open' are real links; Blinkit/Instamart "
        "open a smart search instead.\n"
        "- Results are cached ~10 minutes. The app runs on localhost:8000 "
        "(backend) and Vite (frontend).\n"
        "Rules: answer in the user's language (English, Hindi/Hinglish ok), "
        "keep replies short (max ~5 sentences), be concrete about steps, and "
        "never invent prices - for price questions tell them to hit Compare. "
        "The user's current state: " + store_states + "."
    )
    msgs = [{"role": "system", "content": system}]
    for m in history[-8:]:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and m.get("content"):
            msgs.append({"role": m["role"], "content": str(m["content"])[:600]})
    msgs.append({"role": "user", "content": message[:600]})

    try:
        res = _la._groq().chat.completions.create(
            model=_la._MODEL, messages=msgs,
            temperature=0.5, max_tokens=400, timeout=40,
        )
        reply = _la.clean(res.choices[0].message.content or "")
        if not reply:
            raise ValueError("empty")
        return {"reply": reply}
    except Exception:
        raise HTTPException(503, "The AI assistant is unavailable right now — "
                                  "please try again in a minute.")


@app.post("/api/setup/{store}")
def setup(store: str, q: str = "toothpaste"):
    """One-time manual connect: opens a visible window for the user to
    complete a location / bot-check flow, then saves its cookies."""
    if store not in stores.CONNECTORS:
        from fastapi import HTTPException
        raise HTTPException(404, "Unknown store")

    def flow(page):
        url = {"bigbasket": f"https://www.bigbasket.com/ps/?q={q}",
               "blinkit": "https://blinkit.com",
               "zepto": f"https://www.zeptonow.com/search?query={q}",
               "instamart": f"https://www.swiggy.com/instamart/search?query={q}"}[store]
        page.goto(url, wait_until="domcontentloaded", timeout=60000)

        # one-time auto steps so the user has as little to do as possible
        _auto_location(page, store)
        # give the user up to 3 minutes to finish whatever the store shows
        deadline = time.time() + 180
        did_auto = False
        while time.time() < deadline:
            try:
                body = page.locator("body").inner_text().lower()[:4000]
            except Exception:
                body = ""
            if store == "blinkit":
                try:
                    cont = page.get_by_text("Continue on web")
                    if cont.count():
                        cont.first.click(timeout=3000)
                        page.wait_for_timeout(1500)
                        _auto_location(page, store)
                        continue
                except Exception:
                    pass
            if "access denied" in body or "you have been blocked" in body:
                # visible for the user to solve the challenge by hand
                page.wait_for_timeout(4000)
                continue
            # success when the page renders actual products
            if store == "bigbasket":
                if page.locator('[data-qa="product-name"], [data-qa="product-sku-name"]').count():
                    return {"status": "ok"}
                if not did_auto and time.time() > deadline - 150:
                    did_auto = True          # retry the location flow once
                    _auto_location(page, store)
            elif store == "blinkit":
                if "/s/" in page.url and not _looks_blocked(body):
                    return {"status": "ok"}
                if not did_auto and time.time() > deadline - 150:
                    did_auto = True
                    page.goto(f"https://blinkit.com/s/{q}", wait_until="domcontentloaded",
                              timeout=60000)
            else:
                if _looks_ready(body):
                    return {"status": "ok"}
            page.wait_for_timeout(5000)
        return {"status": "timeout"}

    def _auto_location(page, which_store):
        """Set the delivery location automatically (Mumbai 400001 - served by
        all four stores). Blinkit's challenge puzzle, if shown, stays manual."""
        try:
            if which_store == "bigbasket":
                sel = page.get_by_text("Select Location")
                if sel.count():
                    sel.first.click(timeout=5000)
                    page.wait_for_timeout(2000)
                box = page.locator("input[type='text']").first
                if box.count():
                    box.fill("400001", timeout=5000)
                    page.wait_for_timeout(3000)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(5000)
            elif which_store == "blinkit":
                cur = page.get_by_text("Use my current location")
                if not cur.count():
                    cur = page.get_by_text("Detect my location")
                if cur.count():
                    cur.first.click(timeout=4000)   # uses the granted geolocation (Mumbai)
                    page.wait_for_timeout(6000)
                    return
                box = page.locator(
                    "input[placeholder*='ocation'], input[placeholder*='incode'], "
                    "input[type='text']").first
                if box.count():
                    box.fill("400001", timeout=4000)
                    page.wait_for_timeout(2500)
                    page.keyboard.press("Enter")
                    page.wait_for_timeout(5000)
        except Exception:
            pass

    def _looks_blocked(body: str) -> bool:
        return ("access denied" in body or "blocked" in body)

    def _looks_ready(body: str) -> bool:
        return any(w in body for w in ("₹", "rs.", "add", "add to cart"))

    result = fetcher.browser_job(store, flow, timeout=260)
    if result.get("status") != "ok":
        from fastapi import HTTPException
        raise HTTPException(503, f"{store} setup didn't complete: {result['status']}")
    _cache.clear()   # refresh cached results now that cookies exist
    return {"status": "ok", "store": store}


# ---- Serve the built frontend when deployed as a single service --------------
# Render/Docker sets WEB_DIST; local dev falls back to ../Frontend/dist when
# it exists. Registered last so /api/* and /health keep priority.
_web_dist = None
for _p in (os.environ.get("WEB_DIST"),
           str(Path(__file__).resolve().parent.parent / "Frontend" / "dist")):
    if _p and (Path(_p) / "index.html").exists():
        _web_dist = Path(_p)
        break
if _web_dist:
    app.mount("/", StaticFiles(directory=str(_web_dist), html=True), name="web")
