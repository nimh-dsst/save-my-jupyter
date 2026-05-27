import type {
  ArtifactKind,
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
  readonly tags: readonly string[];
  readonly runLabel: string | null;
  readonly freshness: string;
}

const EMPTY_PLAN_MESSAGE =
  "Nothing will be saved with the current settings. Mark a trigger cell, add watched paths, or enable the notebook file.";

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
    tags: preview.tags,
    runLabel: preview.runLabel,
    freshness: buildFreshnessNote(preview.generatedAt, preview.source),
  };
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
