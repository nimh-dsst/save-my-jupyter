export type ValidationResult =
  | { ok: true; normalizedPath: string }
  | { ok: false; message: string };

const WINDOWS_ABSOLUTE_PATH = /^[A-Za-z]:[\\/]/;

export function validateWatchedPath(path: string): ValidationResult {
  const trimmedPath = path.trim();
  if (trimmedPath.length === 0) {
    return {
      ok: false,
      message: "Watched paths must not be empty."
    };
  }

  if (
    trimmedPath.startsWith("/") ||
    trimmedPath.startsWith("\\\\") ||
    WINDOWS_ABSOLUTE_PATH.test(trimmedPath)
  ) {
    return {
      ok: false,
      message: "Watched paths must be relative."
    };
  }

  const normalizedSegments: string[] = [];
  for (const segment of trimmedPath.split(/[\\/]+/)) {
    if (segment === "" || segment === ".") {
      continue;
    }
    if (segment === "..") {
      return {
        ok: false,
        message: "Watched paths must stay within the notebook or repo root."
      };
    }
    normalizedSegments.push(segment);
  }

  if (normalizedSegments.length === 0) {
    return {
      ok: false,
      message: "Watched paths must include at least one path segment."
    };
  }

  return {
    ok: true,
    normalizedPath: normalizedSegments.join("/")
  };
}
