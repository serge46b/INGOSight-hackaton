import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, isApiError } from "../api";
import { displayText, messageCount, ofThreads, relativeTime } from "../format";

type ThreadItem = {
  id: number;
  subject: string;
  participants: string;
  message_count: number;
  last_message_at: string | null;
  last_message_preview: string;
};

type ThreadPageData = {
  items: ThreadItem[];
  total: number;
  limit: number;
  offset: number;
};

export function ThreadsPage() {
  const [items, setItems] = useState<ThreadItem[]>([]);
  const [total, setTotal] = useState(0);
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [syncing, setSyncing] = useState(false);

  async function load(search = query) {
    setLoading(true);
    setError("");
    try {
      const data = await api<ThreadPageData>(
        `/api/threads?limit=25&offset=0&q=${encodeURIComponent(search)}`,
      );
      setItems(data.items);
      setTotal(data.total);
    } catch (reason) {
      setError(isApiError(reason) ? reason.message : "Нет соединения. Повторите позже");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load("");
  }, []);

  const shown = useMemo(() => items, [items]);

  async function onSync() {
    setSyncing(true);
    setError("");
    try {
      await api("/api/sync", { method: "POST" });
      for (let attempt = 0; attempt < 600; attempt += 1) {
        const status = await api<{ state: string; error: { message: string } | null }>("/api/sync/status");
        if (status.state !== "running") {
          if (status.state === "error") {
            setError(status.error?.message || "Не удалось подключиться к почте. Проверьте настройки");
          }
          break;
        }
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      await load(query);
    } catch (reason) {
      setError(isApiError(reason) ? reason.message : "Нет соединения. Повторите позже");
    } finally {
      setSyncing(false);
    }
  }

  return (
    <main className="page">
      <input
        className="search"
        placeholder="Поиск по тредам…"
        aria-label="Поиск по тредам"
        value={query}
        onChange={(event) => {
          const value = event.target.value;
          setQuery(value);
          void load(value);
        }}
      />
      {error ? (
        <div className="banner error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={() => void load(query)}>
            Повторить
          </button>
        </div>
      ) : null}
      {loading ? (
        <div className="stack">
          <div className="skeleton" />
          <div className="skeleton" />
        </div>
      ) : null}
      {!loading && shown.length === 0 ? (
        <p className="muted">Писем пока нет. Запустите синхронизацию.</p>
      ) : null}
      <div className="stack">
        {shown.map((thread) => (
          <Link key={thread.id} className="thread-card" to={`/threads/${thread.id}`}>
            <h2>{displayText(thread.subject)}</h2>
            <p className="meta">
              {thread.participants} · {messageCount(thread.message_count)} · {relativeTime(thread.last_message_at)}
            </p>
            {thread.last_message_preview ? (
              <p className="preview">Последнее: «{displayText(thread.last_message_preview)}»</p>
            ) : null}
          </Link>
        ))}
      </div>
      <div className="list-footer">
        <button className="primary" type="button" onClick={() => void onSync()} disabled={syncing}>
          {syncing ? "Синхронизация…" : "Синхронизировать"}
        </button>
        <span className="muted">
          Показано {shown.length} из {ofThreads(total)}
        </span>
      </div>
    </main>
  );
}
