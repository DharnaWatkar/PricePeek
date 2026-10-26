import { useEffect, useRef, useState } from "react";
import { BASE } from "./config";

const STORE_LABEL = {
  zepto: "Zepto",
  instamart: "Swiggy Instamart",
  bigbasket: "BigBasket",
  blinkit: "Blinkit",
};

const SUGGESTIONS = ["toothpaste", "milk", "bread", "maggie", "colgate", "eggs", "basmati rice"];

export default function App() {
  const [q, setQ] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [settingUp, setSettingUp] = useState("");

  async function search(term = q) {
    if (!term.trim()) return;
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const res = await fetch(`${BASE}/api/search?q=${encodeURIComponent(term.trim())}`);
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || "Search failed. Is the backend running?");
      setResult(body);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function connect(store) {
    setSettingUp(store);
    setError("");
    try {
      // opens a real browser window to complete the store's location/bot check once
      const res = await fetch(`${BASE}/api/setup/${store}?q=${encodeURIComponent(q || "toothpaste")}`,
        { method: "POST" });
      const body = await res.json();
      if (!res.ok) throw new Error(body.detail || `${store} setup failed`);
      await search(q || "toothpaste");
    } catch (e) {
      setError(e.message);
    } finally {
      setSettingUp("");
    }
  }

  return (
    <div className="min-h-screen bg-neutral-950 text-neutral-100">
      <div className="max-w-6xl mx-auto px-4 py-10">
        <h1 className="text-3xl font-bold text-center">PricePeek 🛒</h1>
        <p className="text-center text-neutral-400 mt-1">
          Find the lowest price across Blinkit · Zepto · Instamart · BigBasket
        </p>

        <form
          className="mt-8 flex gap-2 max-w-xl mx-auto"
          onSubmit={(e) => { e.preventDefault(); search(); }}
        >
          <input
            className="flex-1 rounded-lg bg-neutral-900 border border-neutral-700 px-4 py-2 outline-none focus:border-emerald-500"
            placeholder="Type anything… e.g. toothpaste"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <button className="bg-emerald-500 hover:bg-emerald-400 text-black font-semibold px-5 rounded-lg">
            {loading ? "Searching…" : "Compare"}
          </button>
        </form>

        <div className="mt-3 flex flex-wrap justify-center gap-2">
          {SUGGESTIONS.map(s => (
            <button key={s}
              className="text-xs px-3 py-1 rounded-full border border-neutral-700 hover:border-emerald-500 text-neutral-400 hover:text-emerald-400"
              onClick={() => { setQ(s); search(s); }}>
              {s}
            </button>
          ))}
        </div>

        {error && <p className="text-red-400 text-center mt-4 text-sm">{error}</p>}
        {loading && <SkeletonGrid />}

        {result && (
          <div className="mt-10">
            {result.cheapest && (
              <div className="rounded-xl border border-emerald-700 bg-emerald-950/40 p-4 mb-4 flex items-center justify-between gap-3">
                <div>
                  <p className="text-emerald-400 text-xs font-semibold uppercase tracking-wide">🏆 Lowest price found</p>
                  <p className="mt-1 text-sm">
                    <b>₹{result.cheapest.price}</b> on {STORE_LABEL[result.cheapest.store]} —{" "}
                    <span className="text-neutral-300">{result.cheapest.name}</span>
                  </p>
                </div>
                <a href={result.cheapest.url} target="_blank" rel="noreferrer"
                  className="text-emerald-400 text-sm underline shrink-0">Open →</a>
              </div>
            )}

            {result.ai && (
              <div className="rounded-xl border border-fuchsia-800 bg-fuchsia-950/30 p-4 mb-6">
                <p className="text-fuchsia-300 text-xs font-semibold uppercase tracking-wide">
                  🤖 AI agent verdict
                </p>
                <p className="mt-1 text-sm text-neutral-200">{result.ai.summary}</p>
                {result.cheapest && result.ai.cheapest_is_unfair && (
                  <p className="mt-2 text-[11px] text-amber-400">
                    ⚠️ The plain "lowest price" above may be a different pack size — the agent compared
                    like-for-like packs before advising.
                  </p>
                )}
                {result.ai.search_reasoning && (
                  <p className="mt-2 text-[11px] text-neutral-400">
                    understood “{result.query}” as “{result.search_term}” — {result.ai.search_reasoning}
                  </p>
                )}
                {!!result.ai.per_store?.length && (
                  <div className="mt-3 flex flex-wrap gap-2">
                    {result.ai.per_store.map((p, i) => (
                      <span key={i} className="text-[11px] px-2 py-1 rounded-full border border-neutral-700 text-neutral-300">
                        {STORE_LABEL[p.store] || p.store}: best ₹{p.best_price} {p.note ? `· ${p.note}` : ""}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}

            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
              {result.stores.map(s => <StoreCard key={s.store} store={s} onConnect={() => connect(s.store)} connecting={settingUp === s.store} />)}
            </div>
          </div>
        )}
        <ChatBot context={result ? { stores: result.stores, query: result.query } : null} />
      </div>
    </div>
  );
}

function StoreCard({ store, onConnect, connecting }) {
  const ok = store.status === "ok";
  const needsSetup = store.status === "needs_setup";
  const items = store.items || [];

  const badge = ok
    ? { cls: "bg-emerald-500/15 text-emerald-400 border-emerald-700", txt: `✓ live · ${items.length} items` }
    : needsSetup
      ? { cls: "bg-amber-500/15 text-amber-400 border-amber-700", txt: "⚙ one-time connect needed" }
      : { cls: "bg-neutral-700/30 text-neutral-400 border-neutral-700", txt: "⚠ error" };

  return (
    <div className="rounded-xl border border-neutral-800 bg-neutral-900/60 flex flex-col overflow-hidden">
      <div className="p-3 flex items-center justify-between gap-2 border-b border-neutral-800">
        <span className="font-semibold">{STORE_LABEL[store.store]}</span>
        <span className={`text-[10px] px-2 py-0.5 rounded-full border ${badge.cls}`}>{badge.txt}</span>
      </div>

      <div className="p-3 flex flex-col gap-3 flex-1">
        {ok && items.map((it, i) => <Item key={i} it={it} />)}
        {ok && !items.length && <p className="text-xs text-neutral-500">No products matched.</p>}
        {needsSetup && (
          <div className="text-center py-6">
            <p className="text-xs text-neutral-400 mb-3">
              {STORE_LABEL[store.store]} needs a one-time manual check.<br />
              A browser window will open — complete it once.
            </p>
            <button onClick={onConnect} disabled={connecting}
              className="bg-amber-500 hover:bg-amber-400 disabled:opacity-50 text-black text-sm font-semibold px-4 py-2 rounded-lg">
              {connecting ? "Browser is open…" : "Connect store"}
            </button>
          </div>
        )}
        {store.status === "error" && (
          <p className="text-xs text-red-400">{store.error || "Something went wrong."}</p>
        )}
      </div>

      <a href={store.search_url} target="_blank" rel="noreferrer"
        className="text-center text-xs text-neutral-400 hover:text-emerald-400 py-2 border-t border-neutral-800">
        open on {STORE_LABEL[store.store]} →
      </a>
    </div>
  );
}

function Item({ it }) {
  const off = it.mrp > it.price ? Math.round(((it.mrp - it.price) / it.mrp) * 100) : 0;
  return (
    <a href={it.url} target="_blank" rel="noreferrer"
      className="flex gap-3 items-center group">
      {it.image
        ? <img src={it.image} alt="" className="w-14 h-14 object-cover rounded-lg bg-white shrink-0" />
        : <div className="w-14 h-14 rounded-lg bg-neutral-800 shrink-0" />}
      <div className="min-w-0">
        <p className="text-xs leading-snug line-clamp-2 group-hover:text-emerald-400">{it.name}</p>
        <p className="text-sm mt-0.5">
          <b>₹{it.price}</b>
          {off > 0 && <span className="text-neutral-500 line-through ml-2 text-xs">₹{it.mrp}</span>}
          {off > 0 && <span className="text-emerald-400 ml-2 text-xs">{off}% off</span>}
        </p>
        {it.qty && <p className="text-[10px] text-neutral-500">{it.qty}</p>}
      </div>
    </a>
  );
}

function ChatBot({ context }) {
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const boxRef = useRef(null);

  useEffect(() => {
    if (boxRef.current) boxRef.current.scrollTop = boxRef.current.scrollHeight;
  }, [msgs, open]);

  async function send(e) {
    e.preventDefault();
    const message = text.trim();
    if (!message || busy) return;
    setText("");
    const history = msgs.map(m => ({ role: m.role, content: m.text }));
    setMsgs(m => [...m, { role: "user", text: message }, { role: "assistant", text: "...", pending: true }]);
    setBusy(true);
    try {
      const res = await fetch(`${BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, history, context }),
      });
      const body = await res.json();
      const reply = res.ok ? body.reply : (typeof body.detail === "string" ? body.detail : "Something went wrong.");
      setMsgs(m => [...m.slice(0, -1), { role: "assistant", text: reply }]);
    } catch {
      setMsgs(m => [...m.slice(0, -1), { role: "assistant", text: "Can't reach the assistant (is the backend running?)." }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed bottom-5 right-5 z-50 flex flex-col items-end gap-2">
      {open && (
        <div className="w-[340px] h-[440px] rounded-2xl border border-neutral-700 bg-neutral-900 shadow-2xl flex flex-col overflow-hidden">
          <div className="px-4 py-3 border-b border-neutral-800 flex items-center justify-between">
            <span className="text-sm font-semibold">💬 PricePeek assistant</span>
            <button onClick={() => setOpen(false)} className="text-neutral-500 hover:text-neutral-300">✕</button>
          </div>
          <div ref={boxRef} className="flex-1 overflow-y-auto p-3 flex flex-col gap-2 text-sm">
            {msgs.length === 0 && (
              <p className="text-neutral-500 text-xs mt-2">
                Hi! Ask me anything about PricePeek — connecting stores, why a
                price looks odd, what the AI verdict means…
              </p>
            )}
            {msgs.map((m, i) => (
              <div key={i}
                className={`max-w-[85%] px-3 py-2 rounded-xl whitespace-pre-wrap leading-snug
                  ${m.role === "user" ? "self-end bg-emerald-600 text-black" : "self-start bg-neutral-800 text-neutral-200"} ${m.pending ? "animate-pulse" : ""}`}>
                {m.text}
              </div>
            ))}
            {busy && <span className="self-start text-xs text-neutral-500">thinking…</span>}
          </div>
          <form onSubmit={send} className="p-2 border-t border-neutral-800 flex gap-2">
            <input
              className="flex-1 bg-neutral-800 border border-neutral-700 rounded-lg px-3 py-2 text-sm outline-none focus:border-emerald-500"
              placeholder="Type your question…"
              value={text}
              onChange={e => setText(e.target.value)}
            />
            <button disabled={busy} className="bg-emerald-500 hover:bg-emerald-400 disabled:opacity-40 text-black text-sm font-semibold px-3 rounded-lg">➤</button>
          </form>
        </div>
      )}
      <button onClick={() => setOpen(o => !o)}
        className="w-14 h-14 rounded-full bg-fuchsia-600 hover:bg-fuchsia-500 shadow-xl text-2xl">
        💬
      </button>
    </div>
  );
}

function SkeletonGrid() {  return (
    <div className="mt-10 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
      {[0, 1, 2, 3].map(i => (
        <div key={i} className="rounded-xl border border-neutral-800 bg-neutral-900/60 p-3 animate-pulse">
          <div className="h-5 w-2/3 bg-neutral-800 rounded mb-4" />
          {[0, 1, 2].map(j => (
            <div key={j} className="flex gap-3 mb-3">
              <div className="w-14 h-14 bg-neutral-800 rounded-lg shrink-0" />
              <div className="flex-1">
                <div className="h-3 bg-neutral-800 rounded mb-2" />
                <div className="h-3 w-1/2 bg-neutral-800 rounded" />
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
