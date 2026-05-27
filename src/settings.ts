import type { ISettingRegistry } from "@jupyterlab/settingregistry";

import {
  parseUserPreferences,
  type CommitMode,
  type UserPreferences,
} from "./types";

export const PLUGIN_ID = "@save-my-jupyter/extension:plugin";

export const DEFAULT_USER_PREFERENCES: UserPreferences = parseUserPreferences({});

export class UserPreferencesStore {
  private settings: ISettingRegistry.ISettings | null = null;

  constructor(private readonly registry: ISettingRegistry | null) {}

  async load(): Promise<UserPreferences> {
    if (this.registry === null) {
      return DEFAULT_USER_PREFERENCES;
    }
    this.settings = await this.registry.load(PLUGIN_ID);
    return this.current();
  }

  current(): UserPreferences {
    if (this.settings === null) {
      return DEFAULT_USER_PREFERENCES;
    }
    return parseUserPreferences(this.settings.composite);
  }

  onChange(listener: (preferences: UserPreferences) => void): void {
    if (this.settings === null) {
      return;
    }
    this.settings.changed.connect(() => {
      listener(this.current());
    });
  }

  async rememberCommitChoice(mode: Exclude<CommitMode, "ask">): Promise<void> {
    if (this.settings === null) {
      return;
    }
    await this.settings.set("defaultCommitMode", mode);
    await this.settings.set("rememberCommitChoice", true);
  }
}
