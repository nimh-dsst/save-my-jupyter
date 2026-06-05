import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

interface NotebookToolbarItem {
  readonly caption?: unknown;
  readonly command?: unknown;
  readonly label?: unknown;
  readonly name?: unknown;
  readonly rank?: unknown;
}

void test("schema keeps the SMJ notebook toolbar entry but not Snapshot Now", () => {
  const notebookToolbarItems = notebookToolbarItemsFromSchema(
    join(process.cwd(), "schema", "plugin.json"),
  );
  assert.deepEqual(notebookToolbarItems, [
    {
      caption: "Open Save My Jupyter sidebar",
      command: "save-my-jupyter:open-panel",
      label: "SMJ",
      name: "save-my-jupyter-open-panel",
      rank: 39,
    },
  ]);
  assert.equal(
    notebookToolbarItems.some(
      (item) =>
        item.command === "save-my-jupyter:snapshot" ||
        item.name === "save-my-jupyter-snapshot",
    ),
    false,
  );
});

function notebookToolbarItemsFromSchema(
  path: string,
): NotebookToolbarItem[] {
  const schema: unknown = JSON.parse(readFileSync(path, "utf8"));
  assert.ok(isRecord(schema));
  const toolbars = schema["jupyter.lab.toolbars"];
  assert.ok(isRecord(toolbars));
  const notebookToolbar = toolbars["Notebook"];
  assert.ok(Array.isArray(notebookToolbar));
  return notebookToolbar.map((item): NotebookToolbarItem => {
    assert.ok(isRecord(item));
    return item;
  });
}

void test("package metadata declares stylesheet and prebuilt output paths", () => {
  const packageMetadata = assertPackageHasStylesheet(
    join(process.cwd(), "package.json"),
  );
  assert.ok(isRecord(packageMetadata["jupyterlab"]));
  assert.equal(
    packageMetadata["jupyterlab"]["outputDir"],
    "save_my_jupyter/labextension",
  );
  assert.equal(packageMetadata["jupyterlab"]["schemaDir"], "schema");
});

function assertPackageHasStylesheet(path: string): Record<string, unknown> {
  const packageMetadata: unknown = JSON.parse(readFileSync(path, "utf8"));
  assert.ok(isRecord(packageMetadata));
  assert.equal(packageMetadata["style"], "style/index.css");
  return packageMetadata;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
