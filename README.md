# PricePeek 🤖🛒

An **AI agent** that finds the lowest price for any product across
**Zepto · Swiggy Instamart · Blinkit** — with reasoning, not just sorting.

## Why it's an AI project

The LLM agent (Groq, `openai/gpt-oss-120b`) acts as the brain in two steps;
the store scrapers are its *tools*:

1. **Understand** — users can type slang or Hindi: `doodh` → milk,
   `chai patti` → tea leaves. The agent returns clean search terms.
2. **Reason** — raw prices per store go back to the agent, which matches the
   SAME pack size across stores, normalises to ₹/unit so a 200 ml pouch can't
   unfairly "win" against a 1 L pack, and writes the final verdict summary.

If the AI step fails, the app degrades gracefully to plain price sorting.

## How it works

No public APIs exist for these apps, so the backend drives a real headful
Chromium per store and captures their internal search APIs / DOM
(`Backend/stores.py`). Cookies persist per store in `Backend/profiles/`
(one-time "Connect store" step for stores with bot-checks; BigBasket is
dropped - their listing API hard-blocks automated browsers).


## Run it

```powershell
# backend
cd Backend
pip install -r requirements.txt      # also: pip install groq python-dotenv
python -m playwright install chromium
venv\Scripts\python -m uvicorn main:app --port 8000 --reload

# frontend
cd ..\Frontend
npm install
npm run dev
```

## Endpoints

- `GET /health`
- `GET /api/search?q=toothpaste` — agent pipeline (understand → scrape → reason), cached 10 minutes
- `POST /api/setup/<store>?q=toothpaste` — one-time interactive connect

## Files

```
Backend/
  main.py        FastAPI app: agent pipeline, /api/setup/<store>
  llm_agent.py   THE AGENT: query understanding + price reasoning (Groq LLM)
  stores.py      one connector per store + JSON parsers (the agent's tools)
  fetcher.py     Playwright lifecycle: headful Chromium per store, cookie profiles
  .env           GROQ_API_KEY
  profiles/      saved cookies per store (auto-created)
Frontend/
  src/App.jsx    search UI, store cards, winner banner + AI verdict panel
```

## Honest caveats

- This is unofficial scraping, built for personal/learning use. If a store
  changes its website, its connector may need a small update.
- Location is fixed to **Mumbai, pincode 400001** — the one place where all
  stores deliver. Prices reflect what those stores show for Mumbai
  (quick-commerce prices vary by pincode and time; delivery fees are not
  included in item price).
