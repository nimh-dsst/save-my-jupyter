import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";

interface ExtensionPackage {
  files?: string[];
  jupyterlab?: {
    extension?: string;
    outputDir?: string;
    schemaDir?: string;
  };
}

interface PluginSchema {
  properties?: Record<string, unknown>;
  title?: string;
  type?: string;
}

function readLabextensionBundle(): string {
  const staticDir = "save_my_jupyter/labextension/static";
  const bundleFiles = readdirSync(staticDir).filter((name) =>
    name.endsWith(".js"),
  );

  assert.ok(
    bundleFiles.length > 0,
    "Expected built labextension JavaScript files in the static bundle.",
  );

  return bundleFiles
    .map((fileName) => readFileSync(join(staticDir, fileName), "utf8"))
    .join("\n");
}

void test("package metadata publishes the settings schema", () => {
  const packageJson = JSON.parse(
    readFileSync("package.json", "utf8"),
  ) as ExtensionPackage;
  const publishedFiles = packageJson.files ?? [];
  const jupyterLabMetadata = packageJson.jupyterlab ?? {};

  assert.equal(jupyterLabMetadata.schemaDir, "schema");
  assert.equal(jupyterLabMetadata.outputDir, "save_my_jupyter/labextension");
  assert.ok(publishedFiles.includes("schema/**/*"));
});

void test("plugin schema defines the stored user preference keys", () => {
  const pluginSchema = JSON.parse(
    readFileSync("schema/plugin.json", "utf8"),
  ) as PluginSchema;

  assert.equal(pluginSchema.title, "Save My Jupyter");
  assert.equal(pluginSchema.type, "object");

  const propertyNames = Object.keys(pluginSchema.properties ?? {}).sort();
  assert.deepEqual(propertyNames, [
    "defaultCommitMode",
    "defaultRunLabel",
    "defaultTags",
    "rememberCommitChoice",
  ]);
});

void test("trigger cell decoration uses a persistent marker element", () => {
  const stylesheet = readFileSync("style/index.css", "utf8");

  assert.match(
    stylesheet,
    /\.jp-Notebook \.jp-Cell\.smj-Cell--trigger::after\s*\{/,
  );
  assert.match(stylesheet, /content:\s*"";/);
  assert.match(stylesheet, /position:\s*absolute;/);
  assert.match(stylesheet, /width:\s*3px;/);
});

void test("trigger cell decoration no longer injects a per-cell button", () => {
  const sourceDecoration = readFileSync(
    "src/notebook/cellTriggerButtons.ts",
    "utf8",
  );
  const compiledDecoration = readFileSync(
    "lib/notebook/cellTriggerButtons.js",
    "utf8",
  );
  const compiledController = readFileSync("lib/panelController.js", "utf8");
  const stylesheet = readFileSync("style/index.css", "utf8");
  const bundledExtension = readLabextensionBundle();

  assert.doesNotMatch(sourceDecoration, /smj-CellTriggerButton/);
  assert.doesNotMatch(compiledDecoration, /smj-CellTriggerButton/);
  assert.doesNotMatch(stylesheet, /smj-CellTriggerButton/);
  assert.match(compiledController, /\.jp-Cell/);
  assert.doesNotMatch(bundledExtension, /smj-CellTriggerButton/);
});

void test("plugin registers a notebook cell context-menu trigger action", () => {
  const pluginSource = readFileSync("src/plugin.ts", "utf8");
  const compiledPlugin = readFileSync("lib/plugin.js", "utf8");
  const bundledExtension = readLabextensionBundle();

  assert.match(pluginSource, /contextMenu\.addItem/);
  assert.match(pluginSource, /\.jp-Notebook \.jp-Cell/);
  assert.match(pluginSource, /contextMenuHitTest/);
  assert.match(compiledPlugin, /contextMenu\.addItem/);
  assert.match(compiledPlugin, /jp-Notebook \.jp-Cell/);
  assert.match(bundledExtension, /contextMenu\.addItem/);
});
