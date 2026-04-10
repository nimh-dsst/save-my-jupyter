import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
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

void test("package metadata publishes the settings schema", () => {
  const packageJson = JSON.parse(
    readFileSync("package.json", "utf8")
  ) as ExtensionPackage;
  const publishedFiles = packageJson.files ?? [];
  const jupyterLabMetadata = packageJson.jupyterlab ?? {};

  assert.equal(jupyterLabMetadata.schemaDir, "schema");
  assert.equal(jupyterLabMetadata.outputDir, "save_my_jupyter/labextension");
  assert.ok(publishedFiles.includes("schema/**/*"));
});

void test("plugin schema defines the stored user preference keys", () => {
  const pluginSchema = JSON.parse(
    readFileSync("schema/plugin.json", "utf8")
  ) as PluginSchema;

  assert.equal(pluginSchema.title, "Save My Jupyter");
  assert.equal(pluginSchema.type, "object");

  const propertyNames = Object.keys(pluginSchema.properties ?? {}).sort();
  assert.deepEqual(propertyNames, [
    "defaultCommitMode",
    "defaultExperimentContext",
    "defaultRunLabel",
    "defaultTags",
    "rememberCommitChoice"
  ]);
});
