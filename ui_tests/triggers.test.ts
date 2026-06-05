import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import {
  ACTIVE_CELL_TRIGGER_CLASS,
  COMMAND_OPEN_PANEL,
  COMMAND_SNAPSHOT,
  COMMAND_TOGGLE_ALL_CELLS_TRIGGER,
  COMMAND_TOGGLE_CELL_TRIGGER,
  NO_CELL_SELECTED_WARNING,
  TRIGGER_CONTEXT_SELECTOR,
  allCellsConfirmMessage,
  activeCellTriggerDescription,
  isAllCellsTriggerMetadata,
  isTriggerMetadata,
  shouldDecorateTriggerCell,
  shouldTriggerOnExecution,
  triggerCellState,
  triggerCellIndexForTarget,
  triggerCellIds,
  triggerCommandLabels,
  triggerModeDescription,
  triggerToggleLabel,
  withSyncedTriggerCellIds,
  withAllCellsTrigger,
  withTrigger,
} from "../src/notebook/triggers";

// --- reading cell trigger state (C-CONFIG-06, C-SNAP-09) ---

void test("isTriggerMetadata is true only when trigger === true", () => {
  assert.equal(isTriggerMetadata({ trigger: true }), true);
  assert.equal(isTriggerMetadata({ trigger: false }), false);
  assert.equal(isTriggerMetadata({}), false);
  assert.equal(isTriggerMetadata(undefined), false);
  assert.equal(isTriggerMetadata(null), false);
  assert.equal(isTriggerMetadata("trigger"), false);
});

void test("isAllCellsTriggerMetadata is true only when all_cells_trigger === true", () => {
  assert.equal(isAllCellsTriggerMetadata({ all_cells_trigger: true }), true);
  assert.equal(isAllCellsTriggerMetadata({ all_cells_trigger: false }), false);
  assert.equal(isAllCellsTriggerMetadata({}), false);
  assert.equal(isAllCellsTriggerMetadata(undefined), false);
});

void test("triggerCellState maps metadata to the active-cell UI state", () => {
  assert.equal(triggerCellState({ trigger: true }), "marked");
  assert.equal(triggerCellState({ trigger: false }), "unmarked");
  assert.equal(triggerCellState(undefined), "unmarked");
});

// --- writing cell trigger state, preserving other keys ---

void test("withTrigger sets the flag and preserves other metadata", () => {
  const next = withTrigger({ trigger: false, note: "keep" }, true);
  assert.equal(next["trigger"], true);
  assert.equal(next["note"], "keep");
});

void test("withTrigger starts from empty when no prior metadata", () => {
  assert.deepEqual(withTrigger(undefined, true), { trigger: true });
  assert.deepEqual(withTrigger(null, false), { trigger: false });
});

// --- notebook-level all-cells trigger (C-SNAP-09) ---

void test("withAllCellsTrigger sets all_cells_trigger and preserves keys", () => {
  const next = withAllCellsTrigger({ watched_paths: ["outputs"] }, true);
  assert.equal(next["all_cells_trigger"], true);
  assert.deepEqual(next["watched_paths"], ["outputs"]);
});

// --- denormalized trigger_cell_ids (C-CONFIG-06) ---

void test("triggerCellIds collects marked cell ids in order", () => {
  assert.deepEqual(
    triggerCellIds([
      { id: "a", trigger: true },
      { id: "b", trigger: false },
      { id: "c", trigger: true },
    ]),
    ["a", "c"],
  );
});

void test("withSyncedTriggerCellIds preserves metadata while replacing denormalized ids", () => {
  assert.deepEqual(
    withSyncedTriggerCellIds(
      {
        all_cells_trigger: true,
        watched_paths: ["outputs"],
        trigger_cell_ids: ["old"],
      },
      [
        { id: "cell-a", trigger: true },
        { id: "cell-b", trigger: false },
      ],
    ),
    {
      all_cells_trigger: true,
      watched_paths: ["outputs"],
      trigger_cell_ids: ["cell-a"],
    },
  );
});

void test("triggerCellIndexForTarget resolves the clicked cell widget", () => {
  const target = { name: "inner" };
  const other = { name: "other" };
  const cells = [
    { node: { contains: (candidate: unknown) => candidate === other } },
    { node: { contains: (candidate: unknown) => candidate === target } },
  ];

  assert.equal(triggerCellIndexForTarget(cells, target), 1);
  assert.equal(triggerCellIndexForTarget(cells, other), 0);
  assert.equal(triggerCellIndexForTarget(cells, { name: "missing" }), null);
});

void test("trigger execution predicate honors marked cells and all-cells mode", () => {
  assert.equal(
    shouldTriggerOnExecution({ all_cells_trigger: false }, { trigger: true }),
    true,
  );
  assert.equal(
    shouldTriggerOnExecution({ all_cells_trigger: true }, { trigger: false }),
    true,
  );
  assert.equal(shouldTriggerOnExecution({}, {}), false);
});

void test("trigger decoration predicate honors effective trigger state", () => {
  assert.equal(
    shouldDecorateTriggerCell({ all_cells_trigger: false }, { trigger: true }),
    true,
  );
  assert.equal(
    shouldDecorateTriggerCell({ all_cells_trigger: true }, { trigger: false }),
    true,
  );
  assert.equal(shouldDecorateTriggerCell({}, {}), false);
});

// --- context-menu label adapts to state (C-CMD-02) ---

void test("triggerToggleLabel adapts to cell state", () => {
  assert.equal(triggerToggleLabel("unmarked"), "Mark Cell As Trigger");
  assert.equal(triggerToggleLabel("marked"), "Unmark Cell As Trigger");
  assert.equal(triggerToggleLabel("unknown"), "Toggle Cell Trigger");
});

void test("trigger panel descriptions expose mode and active-cell state", () => {
  assert.equal(triggerModeDescription(true), "Every executed cell");
  assert.equal(triggerModeDescription(false), "Marked trigger cells only");
  assert.equal(activeCellTriggerDescription("marked"), "Marked as trigger");
  assert.equal(
    activeCellTriggerDescription("unmarked"),
    "Not marked as trigger",
  );
  assert.equal(activeCellTriggerDescription("unknown"), "No active cell");
});

void test("command and selector constants cover the trigger UI surfaces", () => {
  assert.equal(COMMAND_SNAPSHOT, "save-my-jupyter:snapshot");
  assert.equal(COMMAND_OPEN_PANEL, "save-my-jupyter:open-panel");
  assert.equal(
    COMMAND_TOGGLE_CELL_TRIGGER,
    "save-my-jupyter:toggle-cell-trigger",
  );
  assert.equal(
    COMMAND_TOGGLE_ALL_CELLS_TRIGGER,
    "save-my-jupyter:toggle-all-cells-trigger",
  );
  assert.equal(TRIGGER_CONTEXT_SELECTOR, ".jp-Notebook .jp-Cell");
  assert.equal(ACTIVE_CELL_TRIGGER_CLASS, "smj-Cell--trigger");
});

void test("trigger command labels match the palette contract", () => {
  assert.deepEqual(triggerCommandLabels, {
    markCell: "Mark Cell As Trigger",
    openPanel: "Open Snapshot Settings",
    snapshot: "Snapshot Now",
    toggleAllCells: "Toggle All Cells As Triggers",
    toggleCell: "Toggle Cell Trigger",
    unmarkCell: "Unmark Cell As Trigger",
  });
});

void test("trigger-cell decoration has visible left-edge accent styles", () => {
  const stylesheet = readFileSync("style/index.css", "utf8");
  assert.match(
    stylesheet,
    /\.jp-Notebook \.jp-Cell\.smj-Cell--trigger::after\s*\{/,
  );
  assert.match(
    stylesheet,
    /\.jp-Notebook \.jp-Cell\.smj-Cell--trigger\s*\{[\s\S]*?box-shadow: inset 4px 0 0 var\(--jp-brand-color1\);/,
  );
  assert.match(
    stylesheet,
    /\.jp-Notebook \.jp-Cell\.smj-Cell--trigger \.jp-Cell-inputWrapper,[\s\S]*?\.jp-Notebook \.jp-Cell\.smj-Cell--trigger \.jp-Cell-outputWrapper\s*\{[\s\S]*?box-shadow: inset 4px 0 0 var\(--jp-brand-color1\);/,
  );
});

// --- all-cells confirm + no-cell warning (C-CMD-03) ---

void test("allCellsConfirmMessage phrases enable vs disable", () => {
  assert.equal(
    allCellsConfirmMessage(true),
    "Every executed cell will trigger snapshots.",
  );
  assert.equal(
    allCellsConfirmMessage(false),
    "Only marked trigger cells will create automatic snapshots.",
  );
});

void test("no-cell warning matches the contract text", () => {
  assert.equal(
    NO_CELL_SELECTED_WARNING,
    "Select a cell before changing trigger status.",
  );
});
