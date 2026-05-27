import type { CommitMode, SnapshotSubmissionResult } from "./types";

export const NOTEBOOK_UPLOAD_WARNING =
  "Snapshots upload the full notebook with all outputs (stdout, stderr, rendered data, and embedded figures). Clear sensitive outputs before saving.";

export function formatSnapshotSubmissionStatus(
  result: SnapshotSubmissionResult,
): string {
  switch (result.status) {
    case "accepted":
      return ["Snapshot saved.", ...formatSnapshotReferences(result)].join(" ");
    case "rejected":
      return `Snapshot rejected: ${result.message}`;
  }
}

function formatSnapshotReferences(result: SnapshotSubmissionResult): string[] {
  if (result.status !== "accepted") {
    return [];
  }

  const references = [`Job ${result.jobId}.`];
  if (result.snapshotId !== null) {
    references.push(`Snapshot ${result.snapshotId}.`);
  }
  if (result.commitHash !== null) {
    references.push(
      result.commitCreated
        ? `Commit ${shortenCommit(result.commitHash)} created.`
        : `Existing HEAD ${shortenCommit(result.commitHash)} reused.`,
    );
  }
  if (result.commitUrl !== null) {
    references.push(`Commit URL: ${result.commitUrl}.`);
  }
  if (result.labarchivesDirectoryName !== null) {
    const pageCount =
      result.labarchivesPageCount === null
        ? ""
        : ` (${String(result.labarchivesPageCount)} pages)`;
    references.push(
      `LabArchives directory ${result.labarchivesDirectoryName}${pageCount}.`,
    );
  }
  if (result.labarchivesMetaPageName !== null) {
    references.push(`Metadata page ${result.labarchivesMetaPageName}.`);
    return references;
  }
  if (result.labarchivesMetaPageId !== null) {
    references.push(`Metadata page ${result.labarchivesMetaPageId}.`);
    return references;
  }
  if (result.labarchivesPageName !== null) {
    references.push(`LabArchives page ${result.labarchivesPageName}.`);
  } else if (result.labarchivesPageId !== null) {
    references.push(`LabArchives page ${result.labarchivesPageId}.`);
  }
  return references;
}

function shortenCommit(commitHash: string): string {
  return commitHash.length > 12 ? commitHash.slice(0, 12) : commitHash;
}

export function describeCommitMode(mode: CommitMode): string {
  switch (mode) {
    case "always":
      return "Always commit";
    case "never":
      return "Never commit";
    case "prompt":
      return "Prompt before commit";
  }
}

export function describeTriggerMode(allCellsTrigger: boolean): string {
  return allCellsTrigger ? "Every executed cell" : "Marked trigger cells";
}

export function describeBoolean(value: boolean): string {
  return value ? "Yes" : "No";
}

export function formatStringList(values: readonly string[]): string {
  return values.join(", ") || "(none)";
}

export function formatTemplateValues(values: Record<string, string>): string {
  const entries = Object.entries(values).sort(([left], [right]) =>
    left.localeCompare(right),
  );
  return entries.length === 0
    ? "(none)"
    : entries.map(([key, value]) => `${key}=${value}`).join(", ");
}
