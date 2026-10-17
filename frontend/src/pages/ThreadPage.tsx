import { FormEvent, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, isApiError } from "../api";
import { relativeTime } from "../format";

type Message = {
  id: number;
  from_name: string;
  date: string;
  preview: string;
  body_text: string;
  attachments: string[];
};

type ThreadDetail = {
  id: number;
  subject: string;
  messages: Message[];
  summary: { text: string; stale: boolean } | null;
  draft: { text: string; stale: boolean } | null;
};

const tones = [
  { value: "деловой", label: "деловой" },
  { value: "нейтральный", label: "нейтральный" },
  { value: "дружелюбный", label: "дружелюбный" },
];

export function ThreadPage() {
  const params = useParams();
  const threadId = params.id;
  const [thread, setThread] = useState<ThreadDetail | null>(null);
  const [tab, setTab] = useState<"summary" | "ask" | "draft">("summary");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState("");
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const [tone, setTone] = useState("деловой");
  const [draft, setDraft] = useState("");
  const [copied, setCopied] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const data = await api<ThreadDetail>(`/api/threads/${threadId}`);
      setThread(data);
      setSummary(data.summary?.text ?? "");
      setDraft(data.draft?.text ?? "");
    } catch (reason) {
      setThread(null);
      setError(isApiError(reason) ? reason.message : "Нет соединения. Повторите позже");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, [threadId]);

  async function refreshSummary() {
    setBusy(true);
    setError("");
    try {
      const data = await api<{ summary_text: string }>(`/api/threads/${threadId}/summary`, { method: "POST" });
      setSummary(data.summary_text);
    } catch (reason) {
      setError(isApiError(reason) ? reason.message : "Модель не ответила. Проверьте, запущен ли Ollama");
    } finally {
      setBusy(false);
    }
  }

  async function ask(event: FormEvent) {
    event.preventDefault();
    if (!question.trim()) return;
    setBusy(true);
    setError("");
    try {
      const data = await api<{ answer: string }>(`/api/threads/${threadId}/ask`, {
        method: "POST",
        body: JSON.stringify({ question }),
      });
      setAnswer(data.answer);
    } catch (reason) {
      setError(isApiError(reason) ? reason.message : "Модель не ответила. Проверьте, запущен ли Ollama");
    } finally {
      setBusy(false);
    }
  }

  async function createDraft(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setCopied("");
    try {
      const data = await api<{ draft_text: string }>(`/api/threads/${threadId}/draft`, {
        method: "POST",
        body: JSON.stringify({ tone }),
      });
      setDraft(data.draft_text);
    } catch (reason) {
      setError(isApiError(reason) ? reason.message : "Модель не ответила. Проверьте, запущен ли Ollama");
    } finally {
      setBusy(false);
    }
  }

  async function copyDraft() {
    try {
      await navigator.clipboard.writeText(draft);
      setCopied("Черновик скопирован");
    } catch {
      setCopied("Не удалось скопировать. Выделите текст вручную");
    }
  }

  return (
    <>
      <div className="subbar">
        <Link to="/">← К списку</Link>
        <strong>{thread?.subject || "Тред"}</strong>
      </div>
      <main className="page thread-layout">
        {error ? (
          <div className="banner error span-2" role="alert">
            <span>{error}</span>
            <button type="button" onClick={() => void load()}>
              Повторить
            </button>
          </div>
        ) : null}
        <section className="stack">
          {loading ? <div className="skeleton tall" /> : null}
          {thread?.messages.map((message) => (
            <article key={message.id} className="letter">
              <header>
                <strong>От: {message.from_name}</strong>
                <span>{relativeTime(message.date)}</span>
              </header>
              <p>{message.body_text || message.preview}</p>
              {message.attachments.length > 0 ? (
                <p className="meta">Вложения: {message.attachments.join(", ")}</p>
              ) : null}
            </article>
          ))}
        </section>
        <section className="panel">
          <div className="tabs" role="tablist">
            <button type="button" className={tab === "summary" ? "active" : ""} onClick={() => setTab("summary")}>
              Саммари
            </button>
            <button type="button" className={tab === "ask" ? "active" : ""} onClick={() => setTab("ask")}>
              Чат
            </button>
            <button type="button" className={tab === "draft" ? "active" : ""} onClick={() => setTab("draft")}>
              Черновик
            </button>
          </div>
          {tab === "summary" ? (
            <div>
              <h2>Саммари треда</h2>
              {thread?.summary?.stale ? <p className="hint">Переписка изменилась — обновите саммари.</p> : null}
              {summary ? <pre className="model-text">{summary}</pre> : <p className="muted">Саммари ещё нет.</p>}
              <button className="primary" type="button" onClick={() => void refreshSummary()} disabled={busy || loading}>
                {busy ? "Готовим…" : "Обновить саммари"}
              </button>
            </div>
          ) : null}
          {tab === "ask" ? (
            <form onSubmit={ask}>
              <h2>Вопрос по переписке</h2>
              <label>
                Вопрос
                <textarea value={question} onChange={(event) => setQuestion(event.target.value)} />
              </label>
              <button className="primary" type="submit" disabled={busy || !question.trim()}>
                Спросить
              </button>
              {answer ? <pre className="model-text">{answer}</pre> : null}
            </form>
          ) : null}
          {tab === "draft" ? (
            <form onSubmit={createDraft}>
              <h2>Черновик ответа</h2>
              <label>
                Тон
                <select value={tone} onChange={(event) => setTone(event.target.value)}>
                  {tones.map((item) => (
                    <option key={item.value} value={item.value}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
              <button className="primary" type="submit" disabled={busy || loading}>
                Составить черновик
              </button>
              {draft ? <pre className="model-text">{draft}</pre> : <p className="muted">Черновика ещё нет.</p>}
              <button type="button" onClick={() => void copyDraft()} disabled={!draft}>
                Скопировать в почту
              </button>
              {copied ? <p className="hint">{copied}</p> : null}
              {thread?.draft?.stale ? <p className="hint">Переписка изменилась — составьте черновик заново.</p> : null}
            </form>
          ) : null}
        </section>
      </main>
    </>
  );
}
