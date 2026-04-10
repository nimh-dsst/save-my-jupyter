import type { ISettingRegistry } from "@jupyterlab/settingregistry";

import {
  type UserPreferences,
  parseUserPreferences,
  userPreferencesSchema
} from "./types";

const LOCAL_STORAGE_KEY = "@save-my-jupyter/preferences";

export class UserPreferencesStore {
  constructor(
    private readonly pluginId: string,
    private readonly settingRegistry: ISettingRegistry | null
  ) {}

  async load(): Promise<UserPreferences> {
    if (this.settingRegistry !== null) {
      try {
        const settings = await this.settingRegistry.load(this.pluginId);
        return parseUserPreferences(settings.composite);
      } catch {
        return userPreferencesSchema.parse({});
      }
    }

    try {
      const storedValue = window.localStorage.getItem(LOCAL_STORAGE_KEY);
      if (storedValue === null) {
        return userPreferencesSchema.parse({});
      }
      return parseUserPreferences(JSON.parse(storedValue) as unknown);
    } catch {
      return userPreferencesSchema.parse({});
    }
  }

  async save(preferences: UserPreferences): Promise<void> {
    if (this.settingRegistry !== null) {
      const settings = await this.settingRegistry.load(this.pluginId);
      await settings.set("defaultCommitMode", preferences.defaultCommitMode);
      await settings.set(
        "defaultExperimentContext",
        preferences.defaultExperimentContext
      );
      await settings.set("defaultRunLabel", preferences.defaultRunLabel);
      await settings.set("defaultTags", preferences.defaultTags);
      await settings.set(
        "rememberCommitChoice",
        preferences.rememberCommitChoice
      );
      return;
    }

    window.localStorage.setItem(LOCAL_STORAGE_KEY, JSON.stringify(preferences));
  }
}
