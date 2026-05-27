// Frontend mirror of the Python `# smj:` directive parser
// (save_my_jupyter/application/snapshot/directives.py). Behavior must stay
// identical; the shared fixtures in fixtures/directives.json are exercised by
// both this module's tests and the Python tests to guard against drift
// (contracts C-DIRECTIVE-01/02, C-CONTENT-08).

export interface DirectiveResult {
  readonly runLabel: string | null;
  readonly tags: readonly string[];
}

// Only full-line comments are directives, so a `#` inside a string literal on a
// code line cannot masquerade as one (we parse statically, without tokenizing).
const COMMENT_MARKERS = ["#", "//"] as const;
const PREFIX = "smj:";

export function parseDirectives(
  cellSources: readonly string[],
): DirectiveResult {
  let runLabel: string | null = null;
  const tags: string[] = [];
  const seen = new Set<string>();
  for (const source of cellSources) {
    for (const line of source.split(/\r?\n/)) {
      const body = directiveBody(line);
      if (body === null) {
        continue;
      }
      const { run, tags: lineTags } = parseBody(body);
      if (run !== null && runLabel === null) {
        runLabel = run;
      }
      for (const tag of lineTags) {
        if (!seen.has(tag)) {
          seen.add(tag);
          tags.push(tag);
        }
      }
    }
  }
  return { runLabel, tags };
}

/** Union tags across sources, whitespace-trimmed and de-duplicated in
 * first-seen order (contract C-CONTENT-08). */
export function mergeTags(
  ...sources: readonly (readonly string[])[]
): string[] {
  const merged: string[] = [];
  const seen = new Set<string>();
  for (const source of sources) {
    for (const tag of source) {
      const trimmed = tag.trim();
      if (trimmed && !seen.has(trimmed)) {
        seen.add(trimmed);
        merged.push(trimmed);
      }
    }
  }
  return merged;
}

function directiveBody(line: string): string | null {
  const stripped = line.replace(/^\s+/, "");
  for (const marker of COMMENT_MARKERS) {
    if (stripped.startsWith(marker)) {
      const comment = stripped.slice(marker.length).replace(/^\s+/, "");
      if (comment.slice(0, PREFIX.length).toLowerCase() === PREFIX) {
        return comment.slice(PREFIX.length).trim();
      }
      return null;
    }
  }
  return null;
}

function parseBody(body: string): { run: string | null; tags: string[] } {
  let run: string | null = null;
  const tags: string[] = [];
  for (const pair of body.split(";")) {
    const equals = pair.indexOf("=");
    if (equals === -1) {
      continue;
    }
    const key = pair.slice(0, equals).trim().toLowerCase();
    const value = pair.slice(equals + 1).trim();
    if (key === "run") {
      if (run === null && value) {
        run = value;
      }
    } else if (key === "tags") {
      for (const tag of value.split(",")) {
        const trimmed = tag.trim();
        if (trimmed) {
          tags.push(trimmed);
        }
      }
    }
  }
  return { run, tags };
}
