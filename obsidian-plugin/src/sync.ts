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

export interface DeckInfo {
  id: number;
  name: string;
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

function authHeaders(token: string): Record<string, string> {
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

async function requestJson(
  url: string,
  token: string,
  options: { method?: string; body?: string } = {},
): Promise<{ status: number; data: unknown }> {
  try {
    const response = await requestUrl({
      url,
      method: options.method ?? "GET",
      headers: authHeaders(token),
      body: options.body,
      throw: false,
    });
    let data: unknown;
    try {
      data = response.json;
    } catch {
      data = undefined;
    }
    return { status: response.status, data };
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new SyncError(
      `Не удалось подключиться к серверу.\nПроверьте интернет-соединение.\n${detail}`,
      "network",
    );
  }
}

function raiseForStatus(status: number): void {
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
    throw new SyncError("Некорректные данные в запросе.", "validation");
  }
  if (status === 400) {
    throw new SyncError("Ошибка запроса к серверу.", "validation");
  }
  if (status < 200 || status >= 300) {
    throw new SyncError(`Ошибка сервера (HTTP ${status}).`, "server");
  }
}

export async function fetchDecks(serverUrl: string, token: string): Promise<DeckInfo[]> {
  const base = serverUrl.replace(/\/+$/, "");
  const { status, data } = await requestJson(`${base}/api/v1/decks`, token);
  raiseForStatus(status);
  if (typeof data !== "object" || data === null || !("decks" in data) || !Array.isArray((data as { decks: unknown }).decks)) {
    throw new SyncError("Некорректный формат ответа сервера.", "format");
  }
  return ((data as { decks: DeckInfo[] }).decks || []).map((d) => ({
    id: Number(d.id),
    name: String(d.name),
  }));
}

export async function createDeck(
  serverUrl: string,
  token: string,
  name: string,
): Promise<DeckInfo> {
  const base = serverUrl.replace(/\/+$/, "");
  const { status, data } = await requestJson(`${base}/api/v1/decks`, token, {
    method: "POST",
    body: JSON.stringify({ name }),
  });
  if (status === 400) {
    const detail =
      typeof data === "object" && data && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : "Не удалось создать колоду.";
    throw new SyncError(detail, "validation");
  }
  raiseForStatus(status);
  if (typeof data !== "object" || data === null || !("id" in data) || !("name" in data)) {
    throw new SyncError("Некорректный формат ответа сервера.", "format");
  }
  return {
    id: Number((data as DeckInfo).id),
    name: String((data as DeckInfo).name),
  };
}

export async function syncCards(
  serverUrl: string,
  token: string,
  sourceFile: string,
  deck: string | null,
  cards: ParsedCard[],
): Promise<SyncResult> {
  const base = serverUrl.replace(/\/+$/, "");
  const url = `${base}/api/v1/sync`;

  const { status, data } = await requestJson(url, token, {
    method: "POST",
    body: JSON.stringify({
      source_file: sourceFile,
      deck,
      cards: cards.map((c) => ({
        question: c.question,
        answer: c.answer,
        source_file: sourceFile,
      })),
    }),
  });

  if (status === 400) {
    const detail =
      typeof data === "object" && data && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : "Ошибка синхронизации.";
    throw new SyncError(detail, "validation");
  }
  raiseForStatus(status);

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
