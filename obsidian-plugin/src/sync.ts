import { requestUrl } from "obsidian";

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

  let status: number;
  let data: unknown;

  try {
    // requestUrl обходит CORS-ограничения Obsidian (в отличие от fetch).
    const response = await requestUrl({
      url,
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
      throw: false,
    });
    status = response.status;
    try {
      data = response.json;
    } catch {
      data = undefined;
    }
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new SyncError(
      `Не удалось подключиться к серверу.\nПроверьте URL сервера и интернет-соединение.\n${detail}`,
      "network",
    );
  }

  if (status === 401) {
    throw new SyncError(
      "Токен недействителен.\nПолучите новый токен через Telegram-бота.",
      "auth",
    );
  }

  if (status === 413) {
    throw new SyncError("Превышен размер запроса.", "payload");
  }

  if (status === 422) {
    throw new SyncError("Некорректные карточки в запросе.", "validation");
  }

  if (status < 200 || status >= 300) {
    throw new SyncError(`Ошибка сервера (HTTP ${status}).`, "server");
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
