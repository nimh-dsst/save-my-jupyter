import { PathExt } from "@jupyterlab/coreutils";

export const REPO_CONFIG_FILENAME = ".save-my-jupyter.toml";
export const INFERRED_TARGET_ROOT_PATH =
  "Notebook Log/{user_email}/{project_name}/{relative_notebook_path}";
export const NO_NOTEBOOK_CONFIG_MESSAGE =
  "Open a notebook before creating a repo config.";
export const STARTER_CONFIG_HINT =
  "Create a starter .save-my-jupyter.toml to share defaults for this workspace.";
export const EXISTING_CONFIG_HINT =
  "This config is already available for the current notebook.";

const PROJECT_MARKERS = [".git", "pyproject.toml", "package.json"] as const;
const DEFAULT_PROJECT_NAME = "save-my-jupyter";

export interface ContentsLike {
  get(path: string, options?: { content?: boolean }): Promise<unknown>;
  save(
    path: string,
    options: { type: "file"; format: "text"; content: string },
  ): Promise<unknown>;
}

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

export async function inspectStarterConfig(
  contents: ContentsLike,
  notebookPath: string,
): Promise<StarterConfigInspection> {
  const rootDirectory = await resolveProjectRoot(contents, notebookPath);
  const configPath = joinPath(rootDirectory, REPO_CONFIG_FILENAME);
  return {
    configPath,
    exists: await exists(contents, configPath),
    rootDirectory,
  };
}

export async function ensureStarterConfig(
  contents: ContentsLike,
  notebookPath: string,
): Promise<StarterConfigResult> {
  const inspection = await inspectStarterConfig(contents, notebookPath);
  if (inspection.exists) {
    return {
      configPath: inspection.configPath,
      message: `Config already exists at ${inspection.configPath}.`,
      rootDirectory: inspection.rootDirectory,
      status: "exists",
    };
  }

  await contents.save(inspection.configPath, {
    content: buildStarterConfig({
      projectName: await projectNameForConfigRoot(
        contents,
        inspection.rootDirectory,
        notebookPath,
      ),
    }),
    format: "text",
    type: "file",
  });
  return {
    configPath: inspection.configPath,
    message: `Created starter config at ${inspection.configPath}.`,
    rootDirectory: inspection.rootDirectory,
    status: "created",
  };
}

export async function resolveProjectRoot(
  contents: Pick<ContentsLike, "get">,
  notebookPath: string,
): Promise<string> {
  const directories = ancestorDirectories(notebookPath);
  for (const directory of directories) {
    if (await exists(contents, joinPath(directory, REPO_CONFIG_FILENAME))) {
      return directory;
    }
  }
  for (const directory of directories) {
    if (await hasProjectMarker(contents, directory)) {
      return directory;
    }
  }
  return notebookDirectory(notebookPath);
}

export function buildStarterConfig(options: {
  readonly projectName: string;
}): string {
  const projectName = tomlString(options.projectName || DEFAULT_PROJECT_NAME);
  return [
    "# Save My Jupyter starter configuration.",
    "# Shared defaults for snapshots created from this workspace.",
    "",
    "[project]",
    `name = "${projectName}"`,
    'repo_root_strategy = "git"',
    "",
    "[defaults]",
    'commit_mode = "ask"',
    "all_cells_trigger = false",
    "watch_paths = []",
    "include_notebook_file = true",
    "include_diff_when_dirty = true",
    "",
    "[labarchives]",
    'target_notebook = "Jupyter Snapshots"',
    `target_root_path = "${INFERRED_TARGET_ROOT_PATH}"`,
    "",
    "[git]",
    'commit_message_template = "snapshot: {notebook_name} {timestamp}"',
    "stage_notebook_on_commit = true",
    "stage_watched_paths_on_commit = false",
    "",
  ].join("\n");
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

function ancestorDirectories(notebookPath: string): string[] {
  const start = notebookDirectory(notebookPath);
  const directories = [start];
  let current = start;
  while (current !== "") {
    current = normalizePath(PathExt.dirname(current));
    directories.push(current);
  }
  return directories;
}

function notebookDirectory(notebookPath: string): string {
  return normalizePath(PathExt.dirname(normalizePath(notebookPath)));
}

async function hasProjectMarker(
  contents: Pick<ContentsLike, "get">,
  directory: string,
): Promise<boolean> {
  for (const marker of PROJECT_MARKERS) {
    if (await visiblePathExists(contents, joinPath(directory, marker))) {
      return true;
    }
  }
  return false;
}

async function visiblePathExists(
  contents: Pick<ContentsLike, "get">,
  path: string,
): Promise<boolean> {
  try {
    return await exists(contents, path);
  } catch {
    return false;
  }
}

async function exists(
  contents: Pick<ContentsLike, "get">,
  path: string,
): Promise<boolean> {
  try {
    await contents.get(path, { content: false });
    return true;
  } catch (error) {
    if (isMissing(error)) {
      return false;
    }
    throw error;
  }
}

function isMissing(error: unknown): boolean {
  const candidate = error as {
    readonly message?: unknown;
    readonly response?: { readonly status?: unknown };
    readonly status?: unknown;
  };
  return (
    candidate.status === 404 ||
    candidate.response?.status === 404 ||
    /(^|\D)404(\D|$)|not found/i.test(
      typeof candidate.message === "string" ? candidate.message : "",
    )
  );
}

async function projectNameForConfigRoot(
  contents: Pick<ContentsLike, "get">,
  rootDirectory: string,
  notebookPath: string,
): Promise<string> {
  return (
    projectNameCandidate(rootDirectory) ??
    (await directoryModelProjectName(contents, rootDirectory)) ??
    projectNameCandidate(notebookDirectory(notebookPath)) ??
    DEFAULT_PROJECT_NAME
  );
}

async function directoryModelProjectName(
  contents: Pick<ContentsLike, "get">,
  directory: string,
): Promise<string | null> {
  try {
    const model = await contents.get(directory, { content: false });
    if (!isRecord(model)) {
      return null;
    }
    const name = model["name"];
    if (typeof name === "string") {
      const candidate = projectNameCandidate(name);
      if (candidate !== null) {
        return candidate;
      }
    }
    const path = model["path"];
    return typeof path === "string" ? projectNameCandidate(path) : null;
  } catch {
    return null;
  }
}

function projectNameCandidate(path: string): string | null {
  const normalized = normalizePath(path);
  const segment = normalized.split("/").filter(Boolean).at(-1);
  if (segment !== undefined && !segment.endsWith(".ipynb")) {
    return segment;
  }
  const parent = normalizePath(PathExt.dirname(normalized));
  const parentSegment = parent.split("/").filter(Boolean).at(-1);
  return parentSegment !== undefined && !parentSegment.endsWith(".ipynb")
    ? parentSegment
    : null;
}

function joinPath(directory: string, name: string): string {
  return directory === "" ? name : PathExt.join(directory, name);
}

function normalizePath(path: string): string {
  const normalized = path.replaceAll("\\", "/").replace(/^\/+/, "");
  return normalized === "." ? "" : normalized;
}

function tomlString(value: string): string {
  return value.replaceAll("\\", "\\\\").replaceAll('"', '\\"');
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
