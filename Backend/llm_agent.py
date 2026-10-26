"""The AI agent layer for PricePeek.

An LLM (Groq - openai/gpt-oss-120b, the same model Outfit Genie used) acts as
the agent's brain in two steps:

1. plan(query)    - expand the user's phrase into good search terms for the
                    stores (handles slang / other languages: "doodh" -> milk)
2. analyze(...)   - the agent reasons over the raw scraped prices: matches the
                    SAME product across stores, normalizes pack sizes so a
                    small pouch can't win unfairly, and writes the verdict.

The store connectors in stores.py stay the agent's "tools"; this file is only
thinking. Everything degrades gracefully to the plain scraper behaviour if the
AI step fails (missing key / API hiccup).
"""

import json
import os
import re

from dotenv import load_dotenv

load_dotenv(override=True)

_MODEL = "openai/gpt-oss-120b"
_client = None


def _groq():
    global _client
    if _client is None:
        from groq import Groq
        _client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return _client


def _json_call(system: str, user: str) -> dict | None:
    """One groq chat completion forced into JSON. None on any failure."""
    if not os.getenv("GROQ_API_KEY"):
        return None
    try:
        res = _groq().chat.completions.create(
            model=_MODEL,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=0.2,
            response_format={"type": "json_object"},
            timeout=30,
        )
        return json.loads(res.choices[0].message.content or "{}")
    except Exception:
        return None


def plan(query: str) -> dict | None:
    """Agent step 1: turn the user input into good store search terms.

    Returns {"search_term": str, "terms": [str], "reasoning": str} or None.
    """
    out = _json_call(
        "You plan product searches for Indian quick-commerce apps "
        "(Blinkit, Zepto, Swiggy Instamart). Users may type slang, Hindi or "
        "imprecise words. Convert the input into 2-4 simple ENGLISH shopping "
        "search terms people would actually type in these apps. "
        'Return ONLY JSON: {"search_term": "<best single term>", '
        '"terms": ["<term1>", "<term2>"], "reasoning": "<one short line>"}. '
        "Examples: 'doodh' -> milk; 'colgate strong teeth' -> colgate toothpaste; "
        "'chai patti' -> tea leaves.",
        query,
    )
    if out and out.get("search_term"):
        out["terms"] = [t for t in (out.get("terms") or []) if t][:4]
        return out
    return None


def analyze(query: str, stores: list[dict]) -> dict | None:
    """Agent step 2: reason over scraped results and write the verdict.

    `stores` is the backend's usual [{store, status, items:[...]}...] payload.
    Returns {"summary": str, "winner": {...}, "per_store": [...], ...} or None.
    """
    slim = []
    for s in stores:
        slim.append({
            "store": s["store"],
            "status": s.get("status"),
            "items": [
                {"name": i["name"], "price": i["price"], "mrp": i["mrp"],
                 "qty": i["qty"]}
                for i in (s.get("items") or [])[:8]
            ],
        })

    out = _json_call(
        "You are a price-comparison agent for Indian quick-commerce apps "
        "(Blinkit, Zepto, Swiggy Instamart - prices in INR, Mumbai). "
        "You receive raw search results per store. Your job:\n"
        "1. Identify the SAME product variant across stores (a 500 ml pouch "
        "vs a 200 ml pouch are NOT the same - compare like with like).\n"
        "2. Judge the best value per store: a higher absolute price can be a "
        "better deal when the pack is bigger (compute rupees per unit/100g). "
        "Prefer the cheapest option for the standard/common pack size.\n"
        "3. Output the overall winner: the cheapest good option for the most "
        "common pack size of this product in Mumbai.\n"
        "Return ONLY JSON:\n"
        '{"summary": "<2-3 sentences in simple English mentioning real '
        'prices and stores>", "winner": {"store": "<store>", "name": '
        '"<exact item name from the data>", "price": <number>, "qty": '
        '"<pack>"}, "per_store": [{"store": "<store>", "best_name": '
        '"<name>", "best_price": <number>, "note": "<pack-size sanity '
        'check, e.g. also 500ml | only a 6-pack available>"}]}. '
        "Never invent items - use only names/prices from the data.",
        json.dumps({"query": query, "stores": slim}, ensure_ascii=False),
    )
    if out and out.get("summary") and out.get("winner"):
        return out
    return None


def clean(text: str) -> str:
    """Strip markdown fences / control noise from LLM prose."""
    text = re.sub(r"```[a-z]*", "", text or "")
    return " ".join(text.split())
