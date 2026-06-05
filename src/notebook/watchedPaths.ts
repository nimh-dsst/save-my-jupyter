export type WatchedPathAddResult =
  | {
      readonly ok: true;
      readonly path: string;
      readonly metadata: Record<string, unknown>;
      readonly watchedPaths: readonly string[];
    }
  | {
      readonly ok: false;
      readonly message: string;
    };

export interface WatchedPathValidationResult {
  readonly ok: boolean;
  readonly path?: string;
  readonly message?: string;
}

const WINDOWS_ABSOLUTE = /^[A-Za-z]:[\\/]/;

export function readWatchedPaths(metadata: unknown): string[] {
  if (
    typeof metadata !== "object" ||
    metadata === null ||
    !Array.isArray((metadata as { watched_paths?: unknown }).watched_paths)
  ) {
    return [];
  }
  const paths: string[] = [];
  for (const item of (metadata as { watched_paths: unknown[] }).watched_paths) {
    if (typeof item !== "string") {
      continue;
    }
    const validation = validateWatchedPathInput(item, paths);
    if (validation.ok && validation.path !== undefined) {
      paths.push(validation.path);
    }
  }
  return paths;
}

export function validateWatchedPathInput(
  raw: string,
  existingPaths: readonly string[] = [],
): WatchedPathValidationResult {
  const trimmed = raw.trim();
  if (trimmed === "") {
    return { ok: false, message: "Tracked paths must not be empty." };
  }
  if (
    trimmed.startsWith("/") ||
    trimmed.startsWith("\\\\") ||
    WINDOWS_ABSOLUTE.test(trimmed)
  ) {
    return { ok: false, message: "Tracked paths must be relative." };
  }

  const segments: string[] = [];
  for (const segment of trimmed.split(/[\\/]+/)) {
    if (segment === "" || segment === ".") {
      continue;
    }
    if (segment === "..") {
      return {
        ok: false,
        message: "Tracked paths must stay within the notebook or repo root.",
      };
    }
    segments.push(segment);
  }
  if (segments.length === 0) {
    return {
      ok: false,
      message: "Tracked paths must include at least one path segment.",
    };
  }

  const path = segments.join("/");
  if (existingPaths.includes(path)) {
    return { ok: false, message: "That tracked path is already listed." };
  }
  return { ok: true, path };
}

export function withWatchedPaths(
  metadata: unknown,
  watchedPaths: readonly string[],
): Record<string, unknown> {
  return { ...asRecord(metadata), watched_paths: [...watchedPaths] };
}

export function withAddedWatchedPath(
  metadata: unknown,
  rawPath: string,
): WatchedPathAddResult {
  const current = readWatchedPaths(metadata);
  const validation = validateWatchedPathInput(rawPath, current);
  if (!validation.ok || validation.path === undefined) {
    return {
      ok: false,
      message: validation.message ?? "Unable to add tracked path.",
    };
  }
  const watchedPaths = [...current, validation.path];
  return {
    ok: true,
    path: validation.path,
    metadata: withWatchedPaths(metadata, watchedPaths),
    watchedPaths,
  };
}

export function withoutWatchedPath(
  metadata: unknown,
  path: string,
): {
  readonly metadata: Record<string, unknown>;
  readonly watchedPaths: readonly string[];
} {
  const watchedPaths = readWatchedPaths(metadata).filter((item) => item !== path);
  return {
    metadata: withWatchedPaths(metadata, watchedPaths),
    watchedPaths,
  };
}

function asRecord(metadata: unknown): Record<string, unknown> {
  return typeof metadata === "object" && metadata !== null
    ? { ...(metadata as Record<string, unknown>) }
    : {};
}
