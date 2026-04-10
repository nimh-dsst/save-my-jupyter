export function parseTagsInput(value: string): string[] {
  return value
    .split(",")
    .map(entry => entry.trim())
    .filter(entry => entry !== "");
}

export function formatTagsInput(tags: readonly string[]): string {
  return tags.join(", ");
}
