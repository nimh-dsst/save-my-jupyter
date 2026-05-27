import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const stylesheet = readFileSync("style/index.css", "utf8");

function ruleFor(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = new RegExp(`${escaped}\\s*\\{(?<body>[^}]*)\\}`, "s").exec(
    stylesheet,
  );
  assert.ok(match?.groups?.["body"], `missing stylesheet rule for ${selector}`);
  return match.groups["body"];
}

void test("rendered panel content has nonzero Jupyter-style padding", () => {
  assert.match(ruleFor(".smj-Panel"), /padding:\s*12px;/);
});

void test("right stack padding is scoped to the Save My Jupyter panel widget", () => {
  const rightStackRule = ruleFor("#jp-right-stack > .smj-PanelWidget");
  assert.match(rightStackRule, /box-sizing:\s*border-box;/);
  assert.match(rightStackRule, /display:\s*flex;/);
  assert.match(rightStackRule, /min-height:\s*0;/);
  assert.match(rightStackRule, /overflow:\s*hidden;/);
  assert.match(rightStackRule, /padding:\s*8px;/);
});

void test("right stack panel body can shrink and scroll within the padded widget", () => {
  const panelRule = ruleFor("#jp-right-stack > .smj-PanelWidget > .smj-Panel");
  assert.match(panelRule, /flex:\s*1 1 auto;/);
  assert.match(panelRule, /min-height:\s*0;/);
  assert.match(panelRule, /width:\s*100%;/);
  assert.match(ruleFor(".smj-Panel"), /overflow-y:\s*auto;/);
});

void test("rendered panel sections keep vertical rhythm without extra outer margins", () => {
  const sectionRule = ruleFor(".smj-Panel section");
  assert.match(sectionRule, /margin:\s*0;/);
  assert.match(sectionRule, /padding:\s*12px 0;/);
});

void test("rendered panel uses scan-friendly hierarchy rows and action stacks", () => {
  const titleRowRule = ruleFor(".smj-SectionTitleRow");
  assert.match(titleRowRule, /display:\s*flex;/);
  assert.match(titleRowRule, /justify-content:\s*space-between;/);

  const actionStackRule = ruleFor(".smj-ActionStack");
  assert.match(actionStackRule, /display:\s*grid;/);
  assert.match(actionStackRule, /gap:\s*8px;/);
});

void test("rendered panel controls use JupyterLab theme variables", () => {
  const buttonRule = ruleFor(".smj-Panel button");
  assert.match(buttonRule, /background:\s*var\(--jp-layout-color1\);/);
  assert.match(buttonRule, /border:\s*1px solid var\(--jp-border-color1\);/);
  assert.match(buttonRule, /font-family:\s*var\(--jp-ui-font-family\);/);

  const inputRule = ruleFor(
    ".smj-Panel input,\n.smj-Panel select,\n.smj-Panel textarea",
  );
  assert.match(inputRule, /background:\s*var\(--jp-input-background\);/);
  assert.match(inputRule, /border:\s*1px solid var\(--jp-input-border-color\);/);
  assert.match(inputRule, /font-family:\s*var\(--jp-ui-font-family\);/);
});

void test("rendered panel badges stay quiet and theme-derived", () => {
  const badgeRule = ruleFor(".smj-Badge");
  assert.match(badgeRule, /background:\s*transparent;/);
  assert.match(badgeRule, /border:\s*1px solid var\(--jp-border-color3\);/);
  assert.doesNotMatch(badgeRule, /color-mix\(/);
  assert.doesNotMatch(ruleFor(".smj-Badge-success"), /color-mix\(/);
  assert.doesNotMatch(ruleFor(".smj-Badge-warning"), /color-mix\(/);
});

void test("rendered panel separates preview subgroups and item lists", () => {
  const subsectionRule = ruleFor(".smj-Subsection + .smj-Subsection");
  assert.match(subsectionRule, /border-top:\s*1px solid var\(--jp-border-color3\);/);
  assert.match(subsectionRule, /padding-top:\s*8px;/);

  assert.match(
    stylesheet,
    /\.smj-ArtifactList,\s*\.smj-ActivityList\s*\{[\s\S]*?list-style:\s*none;/,
  );
});
