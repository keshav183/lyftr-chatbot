import { useEffect, useRef, useState } from "react";

const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");
const newSessionId = () => "s-" + Math.random().toString(36).slice(2, 10) + Date.now().toString(36).slice(-4);

function readableError(status, detail) {
  if (status === 503) return "All AI providers are currently unavailable. Please try again in a moment.";
  if (status === 422) return "That message couldn't be sent. Keep it between 1 and 4000 characters.";
  if (typeof detail === "string") return detail;
  return "Something went wrong. Please try again.";
}

function Meta({ m }) {
  const cached = m.resolution_source === "LLM_CACHE";
  return (
    <div className="meta">
      <span className={"badge " + (cached ? "cache" : "live")} data-testid="meta-source">{m.resolution_source}</span>
      <span>model: <b data-testid="meta-model">{m.model}</b></span>
      <span>latency: <b data-testid="meta-latency">{m.latency_ms} ms</b></span>
      <span>in: <b data-testid="meta-input-tokens">{m.input_tokens}</b></span>
      <span>out: <b data-testid="meta-output-tokens">{m.output_tokens}</b></span>
      {m.key_id && <span className="dim">{m.key_id}{m.fallback_attempts ? ` (+${m.fallback_attempts} failover)` : ""}</span>}
    </div>
  );
}

export default function App() {
  const [sessionId] = useState(newSessionId); // a new session on every page load
  const [items, setItems] = useState([]);
  const [input, setInput] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [simulate, setSimulate] = useState("");
  const [loading, setLoading] = useState(false);
  const endRef = useRef(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [items, loading]);

  async function send() {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    setItems((p) => [...p, { kind: "user", text }]);
    setLoading(true);
    try {
      const body = { session_id: sessionId, message: text };
      if (systemPrompt.trim()) body.system_prompt = systemPrompt.trim();
      const headers = { "Content-Type": "application/json" };
      if (simulate.trim()) headers["X-Simulate-Failure"] = simulate.trim();
      const res = await fetch(`${API_URL}/chat`, { method: "POST", headers, body: JSON.stringify(body) });
      let data = null;
      try { data = await res.json(); } catch { /* non-JSON body */ }
      if (!res.ok) throw { status: res.status, detail: data?.detail };
      setItems((p) => [...p, { kind: "assistant", text: data.reply, meta: data.metadata }]);
    } catch (e) {
      const msg = e?.status ? readableError(e.status, e.detail) : "Can't reach the server. Check your connection and try again.";
      setItems((p) => [...p, { kind: "error", text: msg }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="app">
      <header>
        <h1>LLM Chatbot</h1>
        <span className="dim">session {sessionId}</span>
      </header>

      <details className="settings">
        <summary>Session settings</summary>
        <label>System prompt (optional)
          <textarea data-testid="system-prompt-input" rows={2} value={systemPrompt}
            onChange={(e) => setSystemPrompt(e.target.value)} placeholder="e.g. You are a pirate." />
        </label>
        <label>X-Simulate-Failure header (demo)
          <input value={simulate} onChange={(e) => setSimulate(e.target.value)} placeholder="key_1=429" />
        </label>
      </details>

      <main className="chat">
        {items.length === 0 && <p className="empty">Say hi to start. Send the same first message in a new tab to see <b>LLM_CACHE</b>.</p>}
        {items.map((it, i) =>
          it.kind === "assistant" ? (
            <div key={i} className="msg assistant" data-testid="assistant-message">
              <div className="text">{it.text}</div>
              <Meta m={it.meta} />
            </div>
          ) : it.kind === "error" ? (
            <div key={i} className="msg error" role="alert" data-testid="error-message">{it.text}</div>
          ) : (
            <div key={i} className="msg user" data-testid="user-message">{it.text}</div>
          )
        )}
        {loading && <div className="msg assistant dim">Thinking…</div>}
        <div ref={endRef} />
      </main>

      <footer>
        <textarea data-testid="chat-input" rows={2} value={input} placeholder="Type a message…"
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} />
        <button data-testid="send-button" onClick={send} disabled={loading}>Send</button>
      </footer>
    </div>
  );
}
