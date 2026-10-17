export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const minutes = Math.round((Date.now() - date.getTime()) / 60000);
  if (minutes < 1) return "только что";
  if (minutes < 60) return `${minutes} мин назад`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) {
    const word = hours === 1 ? "час" : hours < 5 ? "часа" : "часов";
    return `${hours} ${word} назад`;
  }
  const days = Math.round(hours / 24);
  if (days === 1) {
    const time = date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
    return `вчера в ${time}`;
  }
  if (days < 7) {
    const word = days < 5 ? "дня" : "дней";
    return `${days} ${word} назад`;
  }
  return date.toLocaleString("ru-RU", {
    day: "numeric",
    month: "long",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function messageCount(count: number): string {
  const tail = count % 10;
  const hundred = count % 100;
  if (tail === 1 && hundred !== 11) return `${count} письмо`;
  if (tail >= 2 && tail <= 4 && (hundred < 12 || hundred > 14)) return `${count} письма`;
  return `${count} писем`;
}

export function ofThreads(count: number): string {
  const tail = count % 10;
  const hundred = count % 100;
  if (tail === 1 && hundred !== 11) return `${count} треда`;
  return `${count} тредов`;
}

export function pluralWord(count: number, one: string, few: string, many: string): string {
  const value = Math.abs(Math.trunc(count));
  const tail = value % 10;
  const hundred = value % 100;
  if (hundred >= 11 && hundred <= 14) return many;
  if (tail === 1) return one;
  if (tail >= 2 && tail <= 4) return few;
  return many;
}

export function displayText(value: string | null | undefined): string {
  const raw = value || "";
  if (!raw) return "";
  const decoded = new DOMParser().parseFromString(raw, "text/html").documentElement.textContent || raw;
  return decoded
    .replace(/[\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u206f\u2800\ufeff]/g, "")
    .replace(/\u00a0/g, " ")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/[ \t]*\n[ \t]*/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function formatStamp(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleString("ru-RU", {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
