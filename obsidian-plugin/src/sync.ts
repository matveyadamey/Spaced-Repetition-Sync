import { ParsedCard } from "./parser";

export interface SyncResult {
  status: string;
  added: number;
  updated: number;
  skipped: number;
  deleted: number;
  errors: string[];
}

export class SyncError extends Error {
  constructor(
    message: string,
    public readonly kind:
      | "network"
      | "auth"
      | "server"
      | "format"
      | "payload"
      | "validation",
  ) {
    super(message);
    this.name = "SyncError";
  }
}

export async function syncCards(
  serverUrl: string,
  token: string,
  cards: ParsedCard[],
): Promise<SyncResult> {
  const base = serverUrl.replace(/\/+$/, "");
  const url = `${base}/api/v1/sync`;

  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        cards: cards.map((c) => ({
          question: c.question,
          answer: c.answer,
          source_file: c.source_file,
        })),
      }),
    });
  } catch {
    throw new SyncError(
      "Не удалось подключиться к серверу.\nПроверьте URL сервера и интернет-соединение.",
      "network",
    );
  }

  if (response.status === 401) {
    throw new SyncError(
      "Токен недействителен.\nПолучите новый токен через Telegram-бота.",
      "auth",
    );
  }

  if (response.status === 413) {
    throw new SyncError("Превышен размер запроса.", "payload");
  }

  if (response.status === 422) {
    throw new SyncError("Некорректные карточки в запросе.", "validation");
  }

  if (!response.ok) {
    throw new SyncError(`Ошибка сервера (HTTP ${response.status}).`, "server");
  }

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new SyncError("Некорректный формат ответа сервера.", "format");
  }

  if (
    typeof data !== "object" ||
    data === null ||
    !("status" in data) ||
    !("added" in data) ||
    !("updated" in data) ||
    !("deleted" in data)
  ) {
    throw new SyncError("Некорректный формат ответа сервера.", "format");
  }

  const result = data as SyncResult;
  return {
    status: result.status,
    added: Number(result.added) || 0,
    updated: Number(result.updated) || 0,
    skipped: Number(result.skipped) || 0,
    deleted: Number(result.deleted) || 0,
    errors: Array.isArray(result.errors) ? result.errors : [],
  };
}

export function formatSyncNotice(result: SyncResult): string {
  return (
    "Синхронизация завершена.\n\n" +
    `Добавлено: ${result.added}\n` +
    `Обновлено: ${result.updated}\n` +
    `Удалено: ${result.deleted}\n` +
    `Ошибок: ${result.errors?.length ?? 0}`
  );
}
