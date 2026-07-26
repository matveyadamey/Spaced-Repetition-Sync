import { App, Notice, Plugin, PluginSettingTab, Setting } from "obsidian";

import { ParsedCard, dedupeByQuestion, parseCards } from "./src/parser";
import { SyncError, formatSyncNotice, syncCards } from "./src/sync";

interface SpacedRepetitionSettings {
  token: string;
  serverUrl: string;
  delimiter: string;
  autoSyncOnStartup: boolean;
}

const DEFAULT_SETTINGS: SpacedRepetitionSettings = {
  token: "",
  serverUrl: "https://your-server.example.com",
  delimiter: "::",
  autoSyncOnStartup: false,
};

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

  async runSync(fromStartup = false) {
    if (!this.settings.token.trim()) {
      new Notice("Укажите токен в настройках плагина.");
      return;
    }
    if (!this.settings.serverUrl.trim()) {
      new Notice("Укажите URL сервера в настройках плагина.");
      return;
    }

    try {
      const files = this.app.vault.getMarkdownFiles();
      const allCards: ParsedCard[] = [];

      for (const file of files) {
        const content = await this.app.vault.read(file);
        const cards = parseCards(content, this.settings.delimiter, file.path);
        allCards.push(...cards);
      }

      const unique = dedupeByQuestion(allCards);
      const result = await syncCards(
        this.settings.serverUrl.trim(),
        this.settings.token.trim(),
        unique,
      );
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
      .setName("Server URL")
      .setDesc("Базовый HTTPS URL сервера без завершающего слэша")
      .addText((text) =>
        text
          .setPlaceholder("https://example.com")
          .setValue(this.plugin.settings.serverUrl)
          .onChange(async (value) => {
            this.plugin.settings.serverUrl = value.trim();
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Delimiter")
      .setDesc("Разделитель между вопросом и ответом")
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
      .setDesc("Автоматическая синхронизация при запуске Obsidian")
      .addToggle((toggle) =>
        toggle.setValue(this.plugin.settings.autoSyncOnStartup).onChange(async (value) => {
          this.plugin.settings.autoSyncOnStartup = value;
          await this.plugin.saveSettings();
        }),
      );
  }
}
