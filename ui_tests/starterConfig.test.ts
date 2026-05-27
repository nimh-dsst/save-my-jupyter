import assert from "node:assert/strict";
import test from "node:test";

import {
  INFERRED_TARGET_ROOT_PATH,
  buildStarterConfig,
  ensureStarterConfig,
  inspectStarterConfig,
  resolveProjectRoot,
  starterConfigButtonLabel,
  starterConfigCreateAvailable,
  starterConfigHint,
  type ContentsLike,
} from "../src/config/starterConfig";

class MissingPathError extends Error {
  readonly response = { status: 404 };
}

class InaccessiblePathError extends Error {
  readonly response = { status: 403 };
}

class FakeContents implements ContentsLike {
  readonly files = new Set<string>();
  readonly inaccessible = new Set<string>();
  readonly models = new Map<string, unknown>();
  readonly saved = new Map<string, string>();

  constructor(
    paths: readonly string[],
    inaccessible: readonly string[] = [],
    models: Record<string, unknown> = {},
  ) {
    paths.forEach((path) => this.files.add(path));
    inaccessible.forEach((path) => this.inaccessible.add(path));
    Object.entries(models).forEach(([path, model]) => {
      this.models.set(path, model);
      this.files.add(path);
    });
  }

  get(path: string): Promise<unknown> {
    if (this.inaccessible.has(path)) {
      return Promise.reject(new InaccessiblePathError(path));
    }
    if (!this.files.has(path)) {
      return Promise.reject(new MissingPathError(path));
    }
    return Promise.resolve(this.models.get(path) ?? { path });
  }

  save(
    path: string,
    options: { type: "file"; format: "text"; content: string },
  ): Promise<unknown> {
    this.files.add(path);
    this.saved.set(path, options.content);
    return Promise.resolve({ path });
  }
}

void test("project root resolves by walking up to a project marker", async () => {
  const contents = new FakeContents(["project/pyproject.toml"]);

  const root = await resolveProjectRoot(
    contents,
    "project/notebooks/run.ipynb",
  );

  assert.equal(root, "project");
});

void test("project root resolves to an existing ancestor repo config before markers", async () => {
  const contents = new FakeContents(["project/.save-my-jupyter.toml"]);

  const root = await resolveProjectRoot(
    contents,
    "project/notebooks/run.ipynb",
  );

  assert.equal(root, "project");
});

void test("inaccessible hidden markers do not block starter config detection", async () => {
  const contents = new FakeContents(
    ["project/package.json"],
    ["project/notebooks/.git", "project/.git"],
  );

  const root = await resolveProjectRoot(
    contents,
    "project/notebooks/run.ipynb",
  );

  assert.equal(root, "project");
});

void test("starter config inspection reports the repo config path", async () => {
  const contents = new FakeContents([
    "project/package.json",
    "project/.save-my-jupyter.toml",
  ]);

  const inspection = await inspectStarterConfig(
    contents,
    "project/notebooks/run.ipynb",
  );

  assert.deepEqual(inspection, {
    configPath: "project/.save-my-jupyter.toml",
    exists: true,
    rootDirectory: "project",
  });
});

void test("ensureStarterConfig writes a starter config when missing", async () => {
  const contents = new FakeContents(["project/pyproject.toml"]);

  const result = await ensureStarterConfig(
    contents,
    "project/notebooks/run.ipynb",
  );

  assert.equal(result.status, "created");
  assert.equal(
    result.message,
    "Created starter config at project/.save-my-jupyter.toml.",
  );
  assert.ok(
    contents.saved
      .get("project/.save-my-jupyter.toml")
      ?.includes(`target_root_path = "${INFERRED_TARGET_ROOT_PATH}"`),
  );
});

void test("ensureStarterConfig uses the config root folder as the project name", async () => {
  const contents = new FakeContents(["project/pyproject.toml"]);

  await ensureStarterConfig(contents, "project/analysis.ipynb");

  assert.ok(
    contents.saved
      .get("project/.save-my-jupyter.toml")
      ?.includes('name = "project"'),
  );
  assert.ok(
    !contents.saved
      .get("project/.save-my-jupyter.toml")
      ?.includes('name = "analysis.ipynb"'),
  );
});

void test("ensureStarterConfig uses the server root folder for root-level notebooks", async () => {
  const contents = new FakeContents([""], [], {
    "": { name: "protein-study", path: "" },
  });

  await ensureStarterConfig(contents, "analysis.ipynb");

  assert.ok(
    contents.saved
      .get(".save-my-jupyter.toml")
      ?.includes('name = "protein-study"'),
  );
  assert.ok(
    !contents.saved
      .get(".save-my-jupyter.toml")
      ?.includes('name = "analysis.ipynb"'),
  );
});

void test("ensureStarterConfig does not overwrite an existing config", async () => {
  const contents = new FakeContents([
    "project/pyproject.toml",
    "project/.save-my-jupyter.toml",
  ]);

  const result = await ensureStarterConfig(contents, "project/run.ipynb");

  assert.equal(result.status, "exists");
  assert.equal(
    result.message,
    "Config already exists at project/.save-my-jupyter.toml.",
  );
  assert.equal(contents.saved.size, 0);
});

void test("ensureStarterConfig does not overwrite an existing ancestor config", async () => {
  const contents = new FakeContents(["project/.save-my-jupyter.toml"]);

  const result = await ensureStarterConfig(
    contents,
    "project/notebooks/run.ipynb",
  );

  assert.equal(result.status, "exists");
  assert.equal(
    result.message,
    "Config already exists at project/.save-my-jupyter.toml.",
  );
  assert.equal(contents.saved.size, 0);
});

void test("starter config create action is available only when config is missing", () => {
  assert.equal(starterConfigCreateAvailable(null), false);
  assert.equal(starterConfigCreateAvailable(false), true);
  assert.equal(starterConfigCreateAvailable(true), false);
  assert.equal(starterConfigButtonLabel(false), "Create starter config");
  assert.equal(starterConfigButtonLabel(true), "Create starter config");
  assert.ok(starterConfigHint(true).includes("already available"));
});

void test("starter config content uses supported contract sections", () => {
  const content = buildStarterConfig({ projectName: 'quoted "project"' });

  assert.ok(content.includes("[project]"));
  assert.ok(content.includes('[defaults]\ncommit_mode = "ask"'));
  assert.ok(content.includes("[labarchives]"));
  assert.ok(content.includes('[git]\ncommit_message_template = "snapshot:'));
  assert.ok(content.includes('name = "quoted \\"project\\""'));
});
