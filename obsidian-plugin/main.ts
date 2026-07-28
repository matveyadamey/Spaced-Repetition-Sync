import { App, Modal, Notice, Plugin, PluginSettingTab, Setting, TFile } from "obsidian";

import { dedupeByQuestion, parseCards } from "./src/parser";
import {
  DeckInfo,
  SyncError,
  createDeck,
  fetchDecks,
  formatSyncNotice,
  syncCards,
} from "./src/sync";

const SERVER_URL = "https://spaced-repetition-sync-production.up.railway.app";
const NO_DECK_LABEL = "без колоды";

interface SpacedRepetitionSettings {
  token: string;
  delimiter: string;
  autoSyncOnStartup: boolean;
}

const DEFAULT_SETTINGS: SpacedRepetitionSettings = {
  token: "",
  delimiter: "::",
  autoSyncOnStartup: false,
};

type DeckPickResult = "cancelled" | "add" | string | null;

class DeckSelectModal extends Modal {
  private settled = false;

  constructor(
    app: App,
    private readonly decks: DeckInfo[],
    private readonly onResult: (result: DeckPickResult) => void,
  ) {
    super(app);
  }

  private finish(result: DeckPickResult) {
    if (this.settled) {
      return;
    }
    this.settled = true;
    this.close();
    this.onResult(result);
  }

  onOpen() {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.createEl("h2", { text: "Выберите колоду" });
    contentEl.createEl("p", {
      text: "Карточки из открытой заметки будут сохранены в выбранную колоду.",
    });

    const list = contentEl.createDiv({ cls: "spaced-rep-deck-list" });

    const addButton = (label: string, result: DeckPickResult) => {
      const btn = list.createEl("button", { text: label });
      btn.style.display = "block";
      btn.style.width = "100%";
      btn.style.marginBottom = "8px";
      btn.addEventListener("click", () => this.finish(result));
    };

    addButton(NO_DECK_LABEL, null);
    for (const deck of this.decks) {
      addButton(deck.name, deck.name);
    }
    addButton("+ Добавить колоду", "add");
  }

  onClose() {
    const { contentEl } = this;
    contentEl.empty();
    // Esc / click outside without choosing
    if (!this.settled) {
      this.settled = true;
      this.onResult("cancelled");
    }
  }
}

export default class SpacedRepetitionPlugin extends Plugin {
  settings: SpacedRepetitionSettings = DEFAULT_SETTINGS;

  async onload() {
    await this.loadSettings();

    this.addCommand({
      id: "sync-cards-to-server",
      name: "Отправить карточки на сервер",
      callback: () => {
        void this.runSync();
      },
    });

    this.addSettingTab(new SpacedRepetitionSettingTab(this.app, this));

    if (this.settings.autoSyncOnStartup) {
      this.app.workspace.onLayoutReady(() => {
        void this.runSync(true);
      });
    }
  }

  chooseDeck(decks: DeckInfo[]): Promise<DeckPickResult> {
    return new Promise((resolve) => {
      const modal = new DeckSelectModal(this.app, decks, resolve);
      modal.open();
    });
  }

  async askDeckName(): Promise<string | null> {
    const name = window.prompt("Название новой колоды:");
    if (name === null) {
      return null;
    }
    const cleaned = name.trim();
    return cleaned || null;
  }

  async runSync(fromStartup = false) {
    if (!this.settings.token.trim()) {
      new Notice("Укажите токен в настройках плагина.");
      return;
    }

    const active = this.app.workspace.getActiveFile();
    if (!(active instanceof TFile) || active.extension !== "md") {
      if (!fromStartup) {
        new Notice("Откройте Markdown-заметку для синхронизации.");
      }
      return;
    }

    try {
      const token = this.settings.token.trim();
      new Notice("Загрузка списка колод…");
      let decks = await fetchDecks(SERVER_URL, token);

      let deckName: string | null = null;
      while (true) {
        const choice = await this.chooseDeck(decks);
        if (choice === "cancelled") {
          new Notice("Синхронизация отменена.");
          return;
        }
        if (choice === "add") {
          const newName = await this.askDeckName();
          if (!newName) {
            continue;
          }
          const created = await createDeck(SERVER_URL, token, newName);
          new Notice(`Колода создана: ${created.name}`);
          decks = await fetchDecks(SERVER_URL, token);
          deckName = created.name;
          break;
        }
        deckName = choice;
        break;
      }

      const content = await this.app.vault.read(active);
      const cards = dedupeByQuestion(
        parseCards(content, this.settings.delimiter, active.path),
      );

      const deckLabel = deckName ?? NO_DECK_LABEL;
      new Notice(`Отправка ${cards.length} карточек в «${deckLabel}»…`);

      const result = await syncCards(SERVER_URL, token, active.path, deckName, cards);
      new Notice(formatSyncNotice(result), 10000);
    } catch (error) {
      if (error instanceof SyncError) {
        new Notice(error.message, 10000);
      } else {
        const detail = error instanceof Error ? error.message : String(error);
        new Notice(`Ошибка синхронизации: ${detail}`, 10000);
      }
      console.error(error);
    }
  }

  async loadSettings() {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }
}

class SpacedRepetitionSettingTab extends PluginSettingTab {
  plugin: SpacedRepetitionPlugin;

  constructor(app: App, plugin: SpacedRepetitionPlugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "Spaced Repetition Sync" });

    new Setting(containerEl)
      .setName("Token")
      .setDesc("Токен авторизации из Telegram-бота (/token)")
      .addText((text) =>
        text
          .setPlaceholder("Вставьте токен")
          .setValue(this.plugin.settings.token)
          .onChange(async (value) => {
            this.plugin.settings.token = value.trim();
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Delimiter")
      .setDesc("Разделитель между вопросом и ответом в карточках")
      .addText((text) =>
        text
          .setPlaceholder("::")
          .setValue(this.plugin.settings.delimiter)
          .onChange(async (value) => {
            this.plugin.settings.delimiter = value || "::";
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Automatic synchronization on startup")
      .setDesc("Автосинхронизация открытой заметки при запуске Obsidian")
      .addToggle((toggle) =>
        toggle.setValue(this.plugin.settings.autoSyncOnStartup).onChange(async (value) => {
          this.plugin.settings.autoSyncOnStartup = value;
          await this.plugin.saveSettings();
        }),
      );
  }
}
