import { App, FuzzySuggestModal, Notice, Plugin, PluginSettingTab, Setting, TFile } from "obsidian";

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
const ADD_DECK_LABEL = "+ Добавить колоду";

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

type DeckChoice = { kind: "deck"; name: string | null } | { kind: "add" };

class DeckSuggestModal extends FuzzySuggestModal<DeckChoice> {
  constructor(
    app: App,
    private readonly choices: DeckChoice[],
    private readonly onPick: (choice: DeckChoice) => void,
  ) {
    super(app);
    this.setPlaceholder("Выберите колоду");
  }

  getItems(): DeckChoice[] {
    return this.choices;
  }

  getItemText(item: DeckChoice): string {
    if (item.kind === "add") {
      return ADD_DECK_LABEL;
    }
    return item.name ?? NO_DECK_LABEL;
  }

  onChooseItem(item: DeckChoice): void {
    this.onPick(item);
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

  async chooseDeck(decks: DeckInfo[]): Promise<"cancelled" | "add" | string | null> {
    return new Promise((resolve) => {
      let settled = false;
      const finish = (value: "cancelled" | "add" | string | null) => {
        if (settled) {
          return;
        }
        settled = true;
        resolve(value);
      };

      const choices: DeckChoice[] = [
        { kind: "deck", name: null },
        ...decks.map((d) => ({ kind: "deck" as const, name: d.name })),
        { kind: "add" },
      ];

      const modal = new DeckSuggestModal(this.app, choices, (choice) => {
        if (choice.kind === "add") {
          finish("add");
          return;
        }
        finish(choice.name);
      });
      const prevClose = modal.onClose.bind(modal);
      modal.onClose = () => {
        prevClose();
        finish("cancelled");
      };
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
      let decks = await fetchDecks(SERVER_URL, token);

      let deckName: string | null = null;
      while (true) {
        const choice = await this.chooseDeck(decks);
        if (choice === "cancelled") {
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

      const result = await syncCards(SERVER_URL, token, active.path, deckName, cards);
      new Notice(formatSyncNotice(result), 8000);
    } catch (error) {
      if (error instanceof SyncError) {
        new Notice(error.message, 8000);
      } else {
        new Notice("Неизвестная ошибка синхронизации.", 8000);
      }
      if (!fromStartup) {
        console.error(error);
      }
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
