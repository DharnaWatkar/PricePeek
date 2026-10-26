# Store connectors: search a store through a real (headful) Chromium page and
# turn its internal APIs / DOM into plain product dicts.
#
#  zepto      -> captures user-search-service/api/v3/search JSON
#  instamart  -> captures /api/instamart/search/v2 JSON
#  bigbasket  -> DOM extraction from the /ps/?q=... page
#  blinkit    -> DOM extraction from the mobile-web search page
#
# Every connector returns {"status": "ok" | "needs_setup" | "empty", "items": [...]}.
# "needs_setup" means the store is showing a bot-check / location wall: the
# user opens the connect window once, completes it manually, and the cookies
# are persisted to profiles/<store>.json for future searches.

import re
import time
from urllib.parse import quote

from fetcher import browser_job


def _link_query(name: str) -> str:
    """Short, store-friendly search phrase for out-links, e.g.
    'Nandini Good Life Toned UHT Milk (Fino Pouch)' -> 'Nandini Good Life Toned'."""
    n = re.sub(r"\\(.*?\\)", " ", name)          # drop bracketed pack info
    n = n.split("|")[0] if "|" in n else n       # drop taglines after '|'
    words = " ".join(n.split())                  # collapse whitespace
    keep = words.split()[:4]                     # first few words are the searchable part
    return " ".join(keep) or name


def _zepto_product_url(name: str, variant) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "p").lower()).strip("-")
    return f"https://www.zeptonow.com/pn/{slug}/pvid/{variant.get('id') or ''}"


def _item(name, price, mrp, qty, image, url):
    return {"name": name.strip()[:120], "price": price, "mrp": mrp,
            "qty": qty, "image": image or "", "url": url or ""}


def search_zepto(page, query):
    """Zepto: drive the mobile-web search page, parse the captured v3 JSON."""
    api_payloads = []

    def on_response(r):
        try:
            if "user-search-service/api/v3/search" in r.url:
                body = r.json()
                if isinstance(body, dict):
                    api_payloads.append(body)
        except Exception:
            pass

    page.on("response", on_response)
    page.goto(f"https://www.zeptonow.com/search?query={quote(query)}",
              wait_until="domcontentloaded", timeout=60000)
    # search results (and their API payload) can arrive late - keep waiting
    parsed = {"items": []}
    deadline = time.time() + 30
    first = True
    while time.time() < deadline:
        parsed = _parse_zepto_payloads(api_payloads)
        if parsed["items"]:
            break
        if first and time.time() > deadline - 24:
            first = False
            try:
                page.goto(f"https://www.zeptonow.com/search?query={quote(query)}",
                          wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
        page.wait_for_timeout(2000)
    items = sorted(parsed["items"], key=lambda i: i["price"])
    return {"status": "ok" if items else "blocked", "items": items[:20]}


def _parse_zepto_payloads(api_payloads):
    products = {}

    def walk(o):
        if isinstance(o, dict):
            if {"product", "productVariant", "sellingPrice"} <= set(o):
                p, v = o["product"], o["productVariant"]
                name = (p.get("name") or p.get("rawTitle") or "").strip()
                if name:
                    price = o["sellingPrice"]
                    mrp = o.get("mrp") or price
                    products.setdefault(name.lower()[:60],
                                        _item(name, price / 100.0, mrp / 100.0,
                                              v.get("formattedPacksize") or "",
                                              _zepto_image(v),
                                              _zepto_product_url(name, v)))
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for sub in o:
                walk(sub)

    def _zepto_image(variant):
        try:
            img = variant["images"][0]
            stem = img["name"].rsplit(".", 1)[0]      # cdn wants the id without .jpeg
            return (f"https://cdn.zeptonow.com/production/ik-seo/"
                    f"tr:w-312,pr-true,f-auto,q-40/{img['path']}/{stem}")
        except Exception:
            return ""

    for payload in api_payloads:
        walk(payload)
    return {"status": "ok" if products else "empty", "items": list(products.values())}


def search_instamart(page, query):
    """Swiggy Instamart: capture /api/instamart/search/v2 responses."""
    payloads = []

    def on_response(r):
        try:
            if "/api/instamart/search" in r.url:
                body = r.json()
                if isinstance(body, dict):
                    payloads.append(body)
        except Exception:
            pass

    page.on("response", on_response)
    target = f"https://www.swiggy.com/instamart/search?query={quote(query)}"
    # products reliably appear on the SECOND visit to the search page
    deadline = time.time() + 46
    visits = 0
    last_visit = time.time()
    while time.time() < deadline:
        items = _parse_instamart_payloads(payloads, query)
        if items:
            break
        if time.time() - last_visit > 10 and visits < 4:
            try:
                page.goto(target, wait_until="domcontentloaded", timeout=60000)
                last_visit = time.time()
                visits += 1
            except Exception:
                pass
        page.wait_for_timeout(2500)
    items = _parse_instamart_payloads(payloads, query)
    items = sorted(items, key=lambda i: i["price"])
    return {"status": "ok" if items else "blocked", "items": items[:20]}


def _parse_instamart_payloads(payloads, query):
    items, seen = [], set()

    def walk(o):
        if isinstance(o, dict):
            v = o.get("price")
            if isinstance(v, dict) and "offerPrice" in v and o.get("displayName"):
                if not (o.get("inventory") or {}).get("inStock", True):
                    return
                name = f'{o.get("brandName", "").strip()} {o["displayName"]}'.strip()
                key = f'{o.get("skuId")}|{o.get("spinId")}'
                if key not in seen and name:
                    seen.add(key)
                    img = ""
                    ids = o.get("imageIds") or []
                    if ids:
                        img = ("https://media-assets.swiggy.com/swiggy/image/upload/"
                               f"fl_lossy,f_auto,q_auto,w_160/{ids[0]}")
                    mrp = float((v.get("mrp") or {}).get("units") or 0)
                    price = float((v.get("offerPrice") or {}).get("units") or 0)
                    items.append(_item(name, price, mrp,
                                       o.get("quantityDescription") or "", img,
                                       f"https://www.swiggy.com/instamart/search?query={quote(query)}"))
            else:
                for sub in o.values():
                    walk(sub)
        elif isinstance(o, list):
            for sub in o:
                walk(sub)

    for payload in payloads:
        for card in (payload.get("data", {}).get("cards") or []):
            walk(card)
    if not items:          # products may live anywhere in the payload
        for payload in payloads:
            walk(payload)
    return items


def _denied(page) -> bool:
    import re
    try:
        low = page.locator("body").inner_text().lower()[:4000]
    except Exception:
        return False
    return bool(re.search(r"access denied|you have been blocked|verify you are", low))


def search_bigbasket(page, query):
    """BigBasket: DOM extraction from the desktop search page."""
    page.goto(f"https://www.bigbasket.com/ps/?q={quote(query)}",
              wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(12000)
    if _denied(page):
        return {"status": "needs_setup", "items": []}

    items = page.evaluate("""
        () => {
          const out = [];
          const names = document.querySelectorAll('[data-qa="product-name"], [data-qa="product-sku-name"]');
          names.forEach(n => {
            let card = n;
            for (let i = 0; i < 7 && card; i++) {
              card = card.parentElement;
              if (card && /₹\\s*\\d/.test(card.textContent || '')) break;
            }
            if (!card) return;
            const t = (card.textContent || '');
            const rupees = [...t.matchAll(/₹\\s*([\\d,]+(?:\\.\\d+)?)/g)].map(m => parseFloat(m[1].replace(/,/g, '')));
            if (!rupees.length) return;
            const img = card.querySelector('img');
            const link = card.closest('a') || card.querySelector('a');
            out.push({ name: n.textContent.trim(),
                       price: Math.min(...rupees),
                       mrp: Math.max(...rupees),
                       qty: '',
                       image: img ? (img.currentSrc || img.src) : '',
                       url: link ? link.href : '' });
          });
          return out;
        }""")
    items = [i for i in items if i["name"]]
    # a dry DOM here almost always means the products never hydrated (bot wall)
    if not items:
        return {"status": "needs_setup", "items": []}
    dedup, final = set(), []
    for i in sorted(items, key=lambda x: x["price"]):
        k = i["name"].lower()[:50]
        if k not in dedup and i["mrp"] > 0:
            dedup.add(k)
            final.append(i)
    return {"status": "ok" if final else "empty", "items": final[:20]}


BLINKIT_EXTRACT = """
() => {
  const out = [];
  const seen = new Set();
  document.querySelectorAll('img').forEach(img => {
    const src = img.currentSrc || img.src || '';
    if (!src.includes('grofers')) return;
    let card = img.parentElement;
    for (let i = 0; i < 6 && card; i++) {
      card = card.parentElement;
      if (card && (card.textContent || '').includes('₹') &&
          (card.textContent || '').length < 400) break;
    }
    if (!card) return;
    const text = (card.innerText || '').trim();
    if (seen.has(text.slice(0, 40))) return;
    seen.add(text.slice(0, 40));
    let name = '', qty = '';
    const prices = [];
    for (const ln of text.split('\\n').map(s => s.trim()).filter(Boolean)) {
      const q = ln.match(/([\\d.]+\\s*(?:g|kg|ml|l|pc)\\b)/i);
      if (q && !qty) qty = q[1];
      const rs = ln.match(/₹\\s?([0-9.,]+)/);
      if (rs) {
        const v = parseFloat(rs[1].replace(/,/g, ''));
        if (v > 0) prices.push(v);
        continue;
      }
      if (!name && ln.length > 2 && !/OFF|MINS|ADD|₹|%/.test(ln)) name = ln;
    }
    if (!name || !prices.length) return;
    out.push({ name: name.slice(0, 120), price: prices[0],
               mrp: prices[1] || prices[0], qty,
               image: src,
               url: '' });
  });
  return out;
}
"""


def search_blinkit(page, query):
    """Blinkit mobile web: search lives at /s/?q=...; tiles hydrate text+price."""
    target = f"https://blinkit.com/s/?q={quote(query)}"
    page.goto(target, wait_until="domcontentloaded", timeout=60000)
    deadline = time.time() + 32
    first = True
    while time.time() < deadline:
        try:
            n = page.evaluate("() => (document.body.innerText.match(/₹\\s?[0-9]/g) || []).length")
        except Exception:
            n = 0
        if n >= 5:
            break
        if first and time.time() > deadline - 20:
            first = False
            try:
                page.goto(target, wait_until="domcontentloaded", timeout=60000)
            except Exception:
                pass
        page.wait_for_timeout(2500)
    if _denied(page):
        return {"status": "needs_setup", "items": []}
    try:
        # blinkit lazy-loads rows while scrolling
        for _ in range(4):
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(1800)
        items = page.evaluate(BLINKIT_EXTRACT)
    except Exception:
        items = []
    dedup, final = set(), []
    for i in sorted(items, key=lambda x: x["price"]):
        k = i["name"].lower()[:50]
        if k not in dedup and i["price"] > 0 and i["mrp"] > 0:
            dedup.add(k)
            i["url"] = f"https://blinkit.com/s/?q={quote(_link_query(i['name']))}"
            final.append(i)
    if not final:
        return {"status": "needs_setup", "items": []}
    return {"status": "ok", "items": final[:20]}


CONNECTORS = {
    "zepto": search_zepto,
    "instamart": search_instamart,
    "blinkit": search_blinkit,
}   # bigbasket dropped: their listing API 403-blocks automated browsers entirely

SEARCH_URL = {
    "zepto": "https://www.zeptonow.com/search?query=",
    "instamart": "https://www.swiggy.com/instamart/search?query=",
    "blinkit": "https://blinkit.com/s/?q=",
    "bigbasket": "https://www.bigbasket.com/ps/?q=",   # kept for the manual link only
}


def search_store(store: str, query: str) -> dict:
    """Entry point used by the API: run one connector."""
    import fetcher
    return fetcher.browser_job(store, lambda page: CONNECTORS[store](page, query),
                               timeout=110)
