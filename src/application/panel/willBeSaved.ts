import type {
  ArtifactKind,
  CommitMode,
  ConfigLayer,
  SnapshotPreviewResponse,
} from "../../types";

export interface WillBeSavedRow {
  readonly kind: ArtifactKind;
  readonly summary: string;
}

export interface DestinationView {
  readonly notebookName: string;
  readonly notebookInferred: boolean;
  readonly notebookLabel: string;
  readonly rootPath: string;
  readonly rootInferred: boolean;
  readonly rootLabel: string;
}

export interface WillBeSavedSection {
  readonly artifacts: readonly WillBeSavedRow[];
  /** Non-null when nothing will be saved; the section is still shown (never hidden). */
  readonly emptyMessage: string | null;
  readonly destination: DestinationView;
  readonly metadataRows: readonly { readonly label: string; readonly value: string }[];
  readonly policyRows: readonly { readonly label: string; readonly value: string }[];
  readonly repoRows: readonly { readonly label: string; readonly value: string }[];
  readonly tags: readonly string[];
  readonly runLabel: string | null;
  readonly freshness: string;
}

const EMPTY_PLAN_MESSAGE =
  "Nothing will be saved with the current settings. Mark a trigger cell, add tracked files, or enable the notebook file.";

/** Inferred config values are labeled inline so the user always sees where data
 * lands — never hover-only (contract C-CONFIG-11). */
export function formatInferredLabel(value: string, inferred: boolean): string {
  return inferred ? `${value} (inferred)` : value;
}

export function buildWillBeSavedSection(
  preview: SnapshotPreviewResponse,
): WillBeSavedSection {
  const artifacts: WillBeSavedRow[] = preview.artifacts.map((artifact) => ({
    kind: artifact.kind,
    summary: artifact.summary,
  }));

  const notebookInferred = isInferred(preview.provenance["targetNotebook"]);
  const rootInferred = isInferred(preview.provenance["targetRootPath"]);

  return {
    artifacts,
    emptyMessage: artifacts.length === 0 ? EMPTY_PLAN_MESSAGE : null,
    destination: {
      notebookName: preview.target.notebookName,
      notebookInferred,
      notebookLabel: formatInferredLabel(
        preview.target.notebookName,
        notebookInferred,
      ),
      rootPath: preview.target.rootPath,
      rootInferred,
      rootLabel: formatInferredLabel(preview.target.rootPath, rootInferred),
    },
    metadataRows: buildMetadataRows(preview),
    policyRows: buildPolicyRows(preview),
    repoRows: buildRepoRows(preview),
    tags: preview.tags,
    runLabel: preview.runLabel,
    freshness: buildFreshnessNote(preview.generatedAt, preview.source),
  };
}

function buildPolicyRows(
  preview: SnapshotPreviewResponse,
): readonly { readonly label: string; readonly value: string }[] {
  const config = preview.effectiveConfig;
  if (config === null) {
    return [];
  }
  const watched =
    config.watchedPaths.length > 0 ? config.watchedPaths.join(", ") : "None";
  const triggerPolicy = config.allCellsTrigger
    ? "Every executed cell"
    : "Marked trigger cells only";
  const diffPolicy = config.includeDiffWhenDirty
    ? "Included when dirty and no commit is created"
    : "Not included";
  const commitMode = formatInferredLabel(
    describeCommitMode(config.commitMode),
    isInferred(preview.provenance["commitMode"]),
  );
  return [
    {
      label: "Notebook file",
      value: config.includeNotebookFile ? "Included with outputs" : "Not included",
    },
    { label: "Tracked files", value: watched },
    { label: "Git commit", value: commitMode },
    { label: "Dirty diff", value: diffPolicy },
    { label: "Trigger policy", value: triggerPolicy },
    {
      label: "Stage notebook",
      value: yesNo(config.stageNotebookOnCommit),
    },
    {
      label: "Stage tracked files",
      value: yesNo(config.stageWatchedPathsOnCommit),
    },
    {
      label: "Commit message",
      value: config.commitMessageTemplate,
    },
    {
      label: "Metadata defaults",
      value: formatKeyValues(config.metadataTemplate),
    },
  ];
}

function buildMetadataRows(
  preview: SnapshotPreviewResponse,
): readonly { readonly label: string; readonly value: string }[] {
  const rows = [
    {
      label: "Run label",
      value: formatInferredLabel(
        preview.runLabel ?? "None",
        preview.runLabel !== null && isInferred(preview.provenance["runLabel"]),
      ),
    },
    {
      label: "Tags",
      value: preview.tags.length > 0 ? preview.tags.join(", ") : "None",
    },
    {
      label: "Notes",
      value: preview.notes ?? "None",
    },
  ];
  for (const [key, value] of Object.entries(preview.extraFields)) {
    rows.push({ label: key, value });
  }
  return rows;
}

function buildRepoRows(
  preview: SnapshotPreviewResponse,
): readonly { readonly label: string; readonly value: string }[] {
  const repo = preview.repo;
  if (repo?.repoRoot === null || repo === null) {
    return [{ label: "Repository", value: "No repository detected" }];
  }
  return [
    { label: "Repository", value: repo.repoRoot },
    { label: "Notebook path", value: repo.relativeNotebookPath ?? "Unavailable" },
    { label: "HEAD", value: repo.headCommit ?? "No HEAD commit" },
    { label: "Dirty state", value: repo.isDirty ? "Dirty" : "Clean" },
    { label: "Remote", value: repo.remoteUrl ?? "No remote URL" },
    {
      label: "Config",
      value: preview.repoConfigLoaded
        ? (preview.repoConfigPath ?? "Loaded")
        : "No .save-my-jupyter.toml loaded",
    },
  ];
}

function describeCommitMode(mode: CommitMode): string {
  switch (mode) {
    case "always":
      return "Create a snapshot commit";
    case "never":
      return "Reuse existing HEAD";
    case "ask":
      return "Ask before snapshot";
  }
}

function yesNo(value: boolean): string {
  return value ? "Yes" : "No";
}

function formatKeyValues(values: Record<string, string>): string {
  const entries = Object.entries(values);
  if (entries.length === 0) {
    return "None";
  }
  return entries.map(([key, value]) => `${key}=${value}`).join(", ");
}

function isInferred(layer: ConfigLayer | undefined): boolean {
  return layer === "inferred" || layer === "fallback";
}

function buildFreshnessNote(
  generatedAt: string,
  source: SnapshotPreviewResponse["source"],
): string {
  const base = `Preview generated ${generatedAt}. Execution recomputes file matches at snapshot time.`;
  if (source === "disk") {
    return `${base} Based on the saved notebook on disk; unsaved edits are not reflected.`;
  }
  return base;
}
