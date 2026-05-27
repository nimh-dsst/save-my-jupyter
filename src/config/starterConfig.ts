export const REPO_CONFIG_FILENAME = ".save-my-jupyter.toml";
export const NO_NOTEBOOK_CONFIG_MESSAGE =
  "Open a notebook before creating a repo config.";
export const STARTER_CONFIG_HINT =
  "Create a starter .save-my-jupyter.toml to share defaults for this workspace.";
export const EXISTING_CONFIG_HINT =
  "This config is already available for the current notebook.";

export interface StarterConfigInspection {
  readonly configPath: string;
  readonly exists: boolean;
  readonly rootDirectory: string;
}

export interface StarterConfigResult {
  readonly configPath: string;
  readonly message: string;
  readonly rootDirectory: string;
  readonly status: "created" | "exists";
}

export function starterConfigButtonLabel(exists: boolean | null): string {
  return exists === null ? "Checking config" : "Create starter config";
}

export function starterConfigCreateAvailable(exists: boolean | null): boolean {
  return exists === false;
}

export function starterConfigHint(exists: boolean | null): string {
  return exists === true ? EXISTING_CONFIG_HINT : STARTER_CONFIG_HINT;
}
