import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

void test("schemas contribute an SMJ notebook toolbar button that opens the sidebar", () => {
  assertSchemaHasOpenPanelToolbarItem(
    join(process.cwd(), "schema", "plugin.json"),
  );
  assertSchemaHasOpenPanelToolbarItem(
    join(
      process.cwd(),
      "save_my_jupyter",
      "labextension",
      "schemas",
      "@save-my-jupyter",
      "extension",
      "plugin.json",
    ),
  );
});

function assertSchemaHasOpenPanelToolbarItem(path: string): void {
  const schema: unknown = JSON.parse(readFileSync(path, "utf8"));
  assert.ok(isRecord(schema));
  const toolbars = schema["jupyter.lab.toolbars"];
  assert.ok(isRecord(toolbars));
  const notebookToolbar = toolbars["Notebook"];
  assert.ok(isArray(notebookToolbar));

  const item = notebookToolbar.find(
    (candidate) =>
      isRecord(candidate) && candidate["name"] === "save-my-jupyter-open-panel",
  );
  assert.ok(isRecord(item));
  assert.equal(item["command"], "save-my-jupyter:open-panel");
  assert.equal(item["label"], "SMJ");
  assert.equal(item["caption"], "Open Save My Jupyter sidebar");
}

void test("package metadata loads the extension stylesheet in prebuilt installs", () => {
  assertPackageHasStylesheet(join(process.cwd(), "package.json"));
  assertPackageHasStylesheet(
    join(process.cwd(), "save_my_jupyter", "labextension", "package.json"),
  );

  const styleImport = readFileSync(
    join(
      process.cwd(),
      "save_my_jupyter",
      "labextension",
      "static",
      "style.js",
    ),
    "utf8",
  );
  assert.match(
    styleImport,
    /import ['"]@save-my-jupyter\/extension\/style\/index\.css['"];/,
  );
});

function assertPackageHasStylesheet(path: string): void {
  const packageMetadata: unknown = JSON.parse(readFileSync(path, "utf8"));
  assert.ok(isRecord(packageMetadata));
  assert.equal(packageMetadata["style"], "style/index.css");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isArray(value: unknown): value is unknown[] {
  return Array.isArray(value);
}
