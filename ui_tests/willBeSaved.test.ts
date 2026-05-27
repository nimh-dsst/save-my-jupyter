import assert from "node:assert/strict";
import test from "node:test";

import {
  buildWillBeSavedSection,
  formatInferredLabel,
} from "../src/application/panel/willBeSaved";
import { parseSnapshotPreviewResponse } from "../src/types";

function previewFixture(
  overrides: Record<string, unknown> = {},
): ReturnType<typeof parseSnapshotPreviewResponse> {
  return parseSnapshotPreviewResponse({
    artifacts: [
      { kind: "notebook", summary: "Notebook (all cells, outputs, metadata)" },
      { kind: "figure", summary: "2 figures from cell outputs" },
    ],
    effectiveConfig: {
      allCellsTrigger: false,
      commitMessageTemplate: "snapshot: {notebook_name}",
      commitMode: "always",
      includeDiffWhenDirty: true,
      includeNotebookFile: true,
      metadataTemplate: { sample: "42" },
      stageNotebookOnCommit: true,
      stageWatchedPathsOnCommit: false,
      target: {
        notebookName: "Jupyter Snapshots",
        rootPath: "Notebook Log/a@b.org/proj/nb.ipynb",
      },
      watchedPaths: ["outputs/*.csv"],
    },
    generatedAt: "2026-05-26T12:00:00.000Z",
    extraFields: { operator: "Ada" },
    notes: "operator note",
    provenance: {
      commitMode: "fallback",
      runLabel: "inferred",
      targetNotebook: "inferred",
      targetRootPath: "inferred",
    },
    repo: {
      headCommit: "abcdef123456",
      isDirty: true,
      relativeNotebookPath: "proj/nb.ipynb",
      remoteUrl: "git@github.com:example/repo.git",
      repoRoot: "/repo",
    },
    repoConfigLoaded: true,
    repoConfigPath: "/repo/.save-my-jupyter.toml",
    runLabel: "training-3",
    source: "frontend",
    tags: ["baseline", "gpu"],
    target: {
      notebookName: "Jupyter Snapshots",
      rootPath: "Notebook Log/a@b.org/proj/nb.ipynb",
    },
    ...overrides,
  });
}

void test("formatInferredLabel appends (inferred) inline only when inferred", () => {
  assert.equal(formatInferredLabel("Jupyter Snapshots", true), "Jupyter Snapshots (inferred)");
  assert.equal(formatInferredLabel("Custom NB", false), "Custom NB");
});

void test("buildWillBeSavedSection lists artifacts in order", () => {
  const section = buildWillBeSavedSection(previewFixture());
  assert.deepEqual(
    section.artifacts.map((row) => row.kind),
    ["notebook", "figure"],
  );
  assert.equal(section.emptyMessage, null);
});

void test("inferred destination is labeled inline, never hidden", () => {
  const section = buildWillBeSavedSection(previewFixture());
  assert.equal(section.destination.notebookInferred, true);
  assert.equal(section.destination.rootInferred, true);
  assert.ok(
    section.destination.notebookLabel.includes("(inferred)"),
    `expected inline inferred label: ${section.destination.notebookLabel}`,
  );
});

void test("explicit destination is not labeled inferred", () => {
  const section = buildWillBeSavedSection(
    previewFixture({ provenance: { targetNotebook: "notebook", targetRootPath: "repo" } }),
  );
  assert.equal(section.destination.notebookInferred, false);
  assert.equal(section.destination.rootInferred, false);
  assert.ok(!section.destination.rootLabel.includes("(inferred)"));
});

void test("empty plan still renders the section with an empty-state message", () => {
  const section = buildWillBeSavedSection(previewFixture({ artifacts: [] }));
  assert.equal(section.artifacts.length, 0);
  assert.ok(
    section.emptyMessage !== null && section.emptyMessage.length > 0,
    "empty plan must show an empty-state message, not hide the section",
  );
});

void test("freshness note mentions execution recompute and the timestamp", () => {
  const section = buildWillBeSavedSection(previewFixture());
  const lowered = section.freshness.toLowerCase();
  assert.ok(lowered.includes("recompute") || lowered.includes("recomputes"));
  assert.ok(section.freshness.includes("2026-05-26T12:00:00.000Z"));
});

void test("disk-sourced preview marks itself as a saved-file fallback", () => {
  const section = buildWillBeSavedSection(previewFixture({ source: "disk" }));
  const lowered = section.freshness.toLowerCase();
  assert.ok(
    lowered.includes("disk") || lowered.includes("saved"),
    `disk preview should disclose the fallback: ${section.freshness}`,
  );
});

void test("tags and run label are carried through", () => {
  const section = buildWillBeSavedSection(previewFixture());
  assert.deepEqual(section.tags, ["baseline", "gpu"]);
  assert.equal(section.runLabel, "training-3");
  assert.ok(
    section.metadataRows.some(
      (row) => row.label === "Run label" && row.value.includes("(inferred)"),
    ),
  );
  assert.ok(
    section.metadataRows.some(
      (row) => row.label === "Notes" && row.value === "operator note",
    ),
  );
  assert.ok(
    section.metadataRows.some(
      (row) => row.label === "operator" && row.value === "Ada",
    ),
  );
});

void test("policy and repository details are included in the review", () => {
  const section = buildWillBeSavedSection(previewFixture());
  assert.ok(section.policyRows.some((row) => row.label === "Git commit"));
  assert.ok(
    section.policyRows.some(
      (row) => row.label === "Git commit" && row.value.includes("(inferred)"),
    ),
  );
  assert.ok(section.policyRows.some((row) => row.value.includes("outputs/*.csv")));
  assert.ok(section.policyRows.some((row) => row.label === "Stage notebook"));
  assert.ok(section.policyRows.some((row) => row.label === "Commit message"));
  assert.ok(section.policyRows.some((row) => row.value.includes("sample=42")));
  assert.ok(section.repoRows.some((row) => row.value === "/repo"));
  assert.ok(section.repoRows.some((row) => row.value === "Dirty"));
});

void test("missing repository is explicit", () => {
  const section = buildWillBeSavedSection(previewFixture({ repo: null }));
  assert.deepEqual(section.repoRows, [
    { label: "Repository", value: "No repository detected" },
  ]);
});
