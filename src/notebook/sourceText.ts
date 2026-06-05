import type { Cell } from "@jupyterlab/cells";

import type { TriggerRun } from "./executionObserver";

export interface TriggerRunContentKeyOptions {
  readonly tags?: readonly string[];
}

export function notebookCellSources(notebookContent: unknown): string[] {
  if (
    typeof notebookContent !== "object" ||
    notebookContent === null ||
    !Array.isArray((notebookContent as { cells?: unknown }).cells)
  ) {
    return [];
  }
  return (notebookContent as { cells: unknown[] }).cells.map((cell) => {
    if (typeof cell !== "object" || cell === null) {
      return "";
    }
    return joinSource((cell as { source?: unknown }).source);
  });
}

export function firstNonBlankSourceLine(cell: Cell): string | null {
  const source = cellSourceText(cell);
  return (
    source
      .split(/\r?\n/)
      .map((line) => line.trim())
      .find((line) => line.length > 0) ?? null
  );
}

export function triggerRunContentKey(
  run: TriggerRun,
  options: TriggerRunContentKeyOptions = {},
): string {
  return JSON.stringify({
    cells: notebookCells(run).map(notebookCellContent),
    tags: normalizedTagSet(options.tags ?? []),
  });
}

function cellSourceText(cell: Cell): string {
  return joinSource((cell.model.toJSON() as { source?: unknown }).source);
}

function notebookCells(run: TriggerRun): Cell[] {
  const notebookWidgets = (run.notebook as { widgets?: unknown }).widgets;
  if (!Array.isArray(notebookWidgets)) {
    return [run.lastCell];
  }
  const cells = notebookWidgets.filter(isCell);
  return cells.length > 0 ? cells : [run.lastCell];
}

function isCell(value: unknown): value is Cell {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as Partial<Cell>).model?.toJSON === "function"
  );
}

function notebookCellContent(cell: Cell): Record<string, unknown> {
  const cellJson = asRecord(cell.model.toJSON());
  const normalized = asRecord(normalizeJsonValue(cellJson ?? {})) ?? {};
  return {
    ...normalized,
    outputs: normalizeJsonValue(cellJson?.["outputs"] ?? []),
    source: joinSource(cellJson?.["source"]),
  };
}

function normalizedTagSet(tags: readonly string[]): string[] {
  return [
    ...new Set(
      tags.map((tag) => tag.trim()).filter((tag) => tag.length > 0),
    ),
  ].sort();
}

function normalizeJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => normalizeJsonValue(item));
  }
  const record = asRecord(value);
  if (record === null) {
    return value;
  }
  const normalized: Record<string, unknown> = {};
  for (const key of Object.keys(record).sort()) {
    if (isNoiseKey(key)) {
      continue;
    }
    normalized[key] = normalizeJsonValue(record[key]);
  }
  return normalized;
}

function isNoiseKey(key: string): boolean {
  return key === "execution_count" || key === "id" || key === "metadata";
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

export function joinSource(source: unknown): string {
  if (typeof source === "string") {
    return source;
  }
  if (Array.isArray(source)) {
    return source.filter((part) => typeof part === "string").join("");
  }
  return "";
}
