import { FormEvent, useEffect, useState } from "react";
import { api, isApiError } from "../api";
import { formatStamp, messageCount, ofThreads, pluralWord } from "../format";

type Settings = {
  imap_mode: string;
  imap_host: string;
  imap_port: number;
  imap_ssl: boolean;
  imap_user: string;
  imap_password_set: boolean;
  model_name: string;
  sync_days: number;
  digest_hours: number;
};

type SyncStatus = {
  state: string;
  finished_at: string | null;
  messages: number;
  threads: number;
  error: { message: string } | null;
  warning: string | null;
};

const empty: Settings = {
  imap_mode: "mock",
  imap_host: "imap.gmail.com",
  imap_port: 993,
  imap_ssl: true,
  imap_user: "",
  imap_password_set: false,
  model_name: "qwen2.5:7b-instruct",
  sync_days: 30,
  digest_hours: 24,
};

export function SettingsPage() {
  const [form, setForm] = useState(empty);
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [fields, setFields] = useState<string[]>([]);
  const [ollama, setOllama] = useState("Проверяем Ollama…");
  const [ollamaOk, setOllamaOk] = useState(false);
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [loadedKey, setLoadedKey] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [settings, status, model] = await Promise.all([
        api<Settings>("/api/settings"),
        api<SyncStatus>("/api/sync/status"),
        api<{ ok: boolean; detail: string }>("/api/ollama/status"),
      ]);
      setForm(settings);
      setLoadedKey(`${settings.imap_mode}|${settings.imap_host}|${settings.imap_user}`);
      setSync(status);
      setOllama(model.detail);
      setOllamaOk(model.ok);
    } catch (reason) {
      setError(isApiError(reason) ? reason.message : "Нет соединения. Повторите позже");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  function payload() {
    const body: Record<string, unknown> = {
      ...form,
      imap_port: Number(form.imap_port),
      sync_days: Number(form.sync_days),
      digest_hours: Number(form.digest_hours),
    };
    if (password.trim()) {
      body.imap_password = password;
    }
    return body;
  }

  async function onSave(event: FormEvent) {
    event.preventDefault();
    setBusy("save");
    setError("");
    setInfo("");
    setFields([]);
    try {
      const saved = await api<Settings>("/api/settings", {
        method: "PUT",
        body: JSON.stringify(payload()),
      });
      setForm(saved);
      setPassword("");
      const nextKey = `${saved.imap_mode}|${saved.imap_host}|${saved.imap_user}`;
      if (loadedKey && nextKey !== loadedKey) {
        setLoadedKey(nextKey);
        setSync(null);
        setInfo("Ящик сменён. Прежние письма убраны — запустите синхронизацию.");
      } else {
        setInfo("Настройки сохранены");
      }
    } catch (reason) {
      if (isApiError(reason)) {
        setError(reason.message);
        setFields(reason.details?.fields ?? []);
      } else {
        setError("Не удалось сохранить. Попробуйте ещё раз");
      }
    } finally {
      setBusy("");
    }
  }

  async function onTest() {
    setBusy("test");
    setError("");
    setInfo("");
    setFields([]);
    try {
      const result = await api<{ message: string }>("/api/settings/test-imap", {
        method: "POST",
        body: JSON.stringify(payload()),
      });
      setInfo(result.message);
    } catch (reason) {
      if (isApiError(reason)) {
        setError(reason.message);
        setFields(reason.details?.fields ?? []);
      } else {
        setError("Не удалось подключиться к почте. Проверьте настройки");
      }
    } finally {
      setBusy("");
    }
  }

  async function onSync() {
    setBusy("sync");
    setError("");
    setInfo("");
    try {
      await api("/api/sync", { method: "POST" });
      for (let attempt = 0; attempt < 600; attempt += 1) {
        const status = await api<SyncStatus>("/api/sync/status");
        setSync(status);
        if (status.state !== "running") {
          if (status.state === "error") {
            setError(status.error?.message || "Не удалось подключиться к почте. Проверьте настройки");
          } else {
            setInfo("Синхронизация завершена");
            if (status.warning) setError(status.warning);
          }
          break;
        }
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
    } catch (reason) {
      setError(isApiError(reason) ? reason.message : "Нет соединения. Повторите позже");
    } finally {
      setBusy("");
    }
  }

  const invalid = (name: string) => (fields.includes(name) ? "invalid" : "");

  return (
    <main className="page">
      <h1>Настройки</h1>
      {loading ? <div className="skeleton" /> : null}
      {error ? (
        <div className="banner error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={() => void load()}>
            Повторить
          </button>
        </div>
      ) : null}
      {info ? <div className="banner ok">{info}</div> : null}
      {!loading ? (
        <form onSubmit={onSave}>
          <section className="card">
            <h2>Почта (IMAP)</h2>
            <label>
              Режим
              <select
                value={form.imap_mode}
                onChange={(event) => setForm({ ...form, imap_mode: event.target.value })}
              >
                <option value="mock">Тестовый ящик</option>
                <option value="imap">IMAP (Gmail и другие)</option>
              </select>
            </label>
            <label>
              Сервер
              <input
                className={invalid("imap_host")}
                value={form.imap_host}
                onChange={(event) => setForm({ ...form, imap_host: event.target.value })}
              />
            </label>
            <label>
              Порт
              <input
                className={`narrow ${invalid("imap_port")}`}
                value={form.imap_port}
                onChange={(event) => setForm({ ...form, imap_port: Number(event.target.value) })}
              />
            </label>
            <label className="check">
              <input
                type="checkbox"
                checked={form.imap_ssl}
                onChange={(event) => setForm({ ...form, imap_ssl: event.target.checked })}
              />
              <span>Защищённое соединение (SSL)</span>
            </label>
            <label>
              Логин
              <input
                value={form.imap_user}
                autoComplete="username"
                onChange={(event) => setForm({ ...form, imap_user: event.target.value })}
              />
            </label>
            <label>
              Пароль
              <input
                type="password"
                value={password}
                autoComplete="current-password"
                placeholder={form.imap_password_set ? "Пароль уже сохранён" : ""}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            <p className="hint">
              Для Gmail укажите пароль приложения: 16 букв из настроек аккаунта Google. Обычный пароль и
              вход через Google здесь не используются.
            </p>
          </section>

          <section className="card">
            <h2>Модель</h2>
            <label>
              Модель
              <select
                value={form.model_name}
                onChange={(event) => setForm({ ...form, model_name: event.target.value })}
              >
                <option value="qwen2.5:7b-instruct">qwen2.5:7b-instruct</option>
                {form.model_name !== "qwen2.5:7b-instruct" ? (
                  <option value={form.model_name}>{form.model_name}</option>
                ) : null}
              </select>
            </label>
            <p className="status-line">
              <span className={ollamaOk ? "dot ok" : "dot bad"} aria-hidden="true" />
              {ollama}
            </p>
          </section>

          <section className="card">
            <h2>Синхронизация</h2>
            <label>
              Забирать письма за
              <span className="inline">
                <input
                  className={`narrow ${invalid("sync_days")}`}
                  value={form.sync_days}
                  onChange={(event) => setForm({ ...form, sync_days: Number(event.target.value) })}
                />
                {pluralWord(Number(form.sync_days) || 0, "день", "дня", "дней")}
              </span>
            </label>
            <p className="hint">В синхронизацию попадут входящие не старше этого срока.</p>
            <label>
              Сводка за последние
              <span className="inline">
                <input
                  className={`narrow ${invalid("digest_hours")}`}
                  value={form.digest_hours}
                  onChange={(event) => setForm({ ...form, digest_hours: Number(event.target.value) })}
                />
                {pluralWord(Number(form.digest_hours) || 0, "час", "часа", "часов")}
              </span>
            </label>
          </section>

          <div className="actions">
            <button className="primary" type="submit" disabled={busy !== ""}>
              Сохранить
            </button>
            <button type="button" onClick={() => void onTest()} disabled={busy !== ""}>
              Проверить подключение
            </button>
            <button type="button" onClick={() => void onSync()} disabled={busy !== ""}>
              {busy === "sync" ? "Синхронизация…" : "Синхронизировать"}
            </button>
          </div>
          {sync?.finished_at ? (
            <p className="hint">
              Последняя синхронизация: {formatStamp(sync.finished_at)} ({ofThreads(sync.threads)},{" "}
              {messageCount(sync.messages)})
            </p>
          ) : (
            <p className="hint">Синхронизация ещё не запускалась</p>
          )}
        </form>
      ) : null}
    </main>
  );
}
