import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, isApiError } from "../api";
import { displayText, formatStamp, pluralWord, relativeTime } from "../format";

type Digest = {
  generated_at: string | null;
  period_hours: number;
  urgent: { thread_id: number; title: string; from_addr: string; date: string | null }[];
  tasks: { id: number; thread_id: number | null; text: string; due_date: string | null; is_done: boolean }[];
  waiting: { thread_id: number; text: string }[];
};

const empty: Digest = {
  generated_at: null,
  period_hours: 24,
  urgent: [],
  tasks: [],
  waiting: [],
};

export function DigestPage() {
  const [digest, setDigest] = useState<Digest>(empty);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      setDigest(await api<Digest>("/api/digest"));
    } catch (reason) {
      setError(isApiError(reason) ? reason.message : "Нет соединения. Повторите позже");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function refresh() {
    setBusy(true);
    setError("");
    try {
      setDigest(await api<Digest>("/api/digest", { method: "POST" }));
    } catch (reason) {
      setError(isApiError(reason) ? reason.message : "Модель не ответила. Проверьте, запущен ли Ollama");
    } finally {
      setBusy(false);
    }
  }

  async function toggle(task: Digest["tasks"][number]) {
    const next = !task.is_done;
    setDigest({
      ...digest,
      tasks: digest.tasks.map((item) => (item.id === task.id ? { ...item, is_done: next } : item)),
    });
    try {
      await api(`/api/tasks/${task.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_done: next }),
      });
    } catch (reason) {
      setError(isApiError(reason) ? reason.message : "Не удалось сохранить. Попробуйте ещё раз");
      void load();
    }
  }

  const titleDate = digest.generated_at ? formatStamp(digest.generated_at) : "ещё не составлялась";
  const hoursWord = pluralWord(digest.period_hours, "час", "часа", "часов");

  return (
    <>
      <div className="subbar">
        <span>
          Утренняя сводка · {titleDate} · за последние {digest.period_hours} {hoursWord}
        </span>
      </div>
      <main className="page">
        {error ? (
          <div className="banner error" role="alert">
            <span>{error}</span>
            <button type="button" onClick={() => void load()}>
              Повторить
            </button>
          </div>
        ) : null}
        {loading ? <div className="skeleton" /> : null}
        <section>
          <h2 className="danger-title">Срочные письма</h2>
          {digest.urgent.length === 0 ? <p className="muted">Срочных писем нет.</p> : null}
          <div className="stack">
            {digest.urgent.map((item) => (
              <article key={`${item.thread_id}-${item.title}`} className="urgent">
                <div>
                  <strong>⚠ {displayText(item.title)}</strong>
                  <p className="meta">
                    От: {item.from_addr} · {relativeTime(item.date)}
                  </p>
                </div>
                <Link to={`/threads/${item.thread_id}`}>Открыть тред</Link>
              </article>
            ))}
          </div>
        </section>
        <section>
          <h2>Задачи</h2>
          {digest.tasks.length === 0 ? <p className="muted">Задач пока нет.</p> : null}
          <div className="card">
            {digest.tasks.map((task) => (
              <label key={task.id} className={task.is_done ? "task done" : "task"}>
                <input type="checkbox" checked={task.is_done} onChange={() => void toggle(task)} />
                <span className="task-body">
                  <span className="task-text">{displayText(task.text)}</span>
                  <span className="meta">{task.due_date ? `Срок: до ${task.due_date}` : "Срок не указан"}</span>
                </span>
              </label>
            ))}
          </div>
        </section>
        <section>
          <h2>Ожидаемые ответы</h2>
          {digest.waiting.length === 0 ? <p className="muted">Ожидаемых ответов нет.</p> : null}
          <div className="card">
            <ul>
              {digest.waiting.map((item) => (
                <li key={`${item.thread_id}-${item.text}`}>
                  <Link to={`/threads/${item.thread_id}`}>{displayText(item.text)}</Link>
                </li>
              ))}
            </ul>
          </div>
        </section>
        <button className="primary" type="button" onClick={() => void refresh()} disabled={busy}>
          {busy ? "Обновляем…" : "Обновить сводку"}
        </button>
      </main>
    </>
  );
}
