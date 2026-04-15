import type { Cell } from "@jupyterlab/cells";
import { circleEmptyIcon, circleIcon } from "@jupyterlab/ui-components";

export interface CellTriggerDecorationOptions {
  isTrigger: boolean;
  onToggle: (cell: Cell) => void;
}

export function syncCellTriggerDecoration(
  cell: Cell,
  options: CellTriggerDecorationOptions
): void {
  const { isTrigger, onToggle } = options;
  cell.node.classList.toggle("smj-Cell--trigger", isTrigger);
  syncCellTriggerButton(cell, isTrigger, onToggle);
  if (isTrigger) {
    cell.node.dataset["smjTrigger"] = "true";
    return;
  }

  delete cell.node.dataset["smjTrigger"];
}

function syncCellTriggerButton(
  cell: Cell,
  isTrigger: boolean,
  onToggle: (cell: Cell) => void
): void {
  const container = resolveTriggerButtonContainer(cell);
  if (container === null) {
    return;
  }

  const inCellToolbar = container.matches(".jp-cell-toolbar");
  container.classList.toggle("smj-CellHeader", !inCellToolbar);
  container.classList.toggle("smj-CellToolbar", inCellToolbar);

  const existingButton = cell.node.querySelector<HTMLButtonElement>(
    ".smj-CellTriggerButton"
  );
  if (existingButton !== null && !container.contains(existingButton)) {
    const existingToolbarItem = existingButton.closest<HTMLElement>(
      ".smj-CellTriggerToolbarItem"
    );
    if (existingToolbarItem !== null) {
      existingToolbarItem.remove();
    } else {
      existingButton.remove();
    }
  }

  let button = container.querySelector<HTMLButtonElement>(".smj-CellTriggerButton");
  if (button === null) {
    button = document.createElement("button");
    button.className = inCellToolbar
      ? "jp-ToolbarButtonComponent smj-CellTriggerButton"
      : "jp-Button jp-mod-minimal smj-CellTriggerButton";
    button.type = "button";
    button.addEventListener("click", event => {
      event.preventDefault();
      event.stopPropagation();
      onToggle(cell);
    });
    if (inCellToolbar) {
      const toolbarItem = document.createElement("div");
      toolbarItem.className = "lm-Widget jp-Toolbar-item smj-CellTriggerToolbarItem";
      toolbarItem.appendChild(button);
      container.appendChild(toolbarItem);
    } else {
      container.appendChild(button);
    }
  }

  const title = isTrigger ? "Unmark cell as a trigger" : "Mark cell as a trigger";
  button.replaceChildren(
    (isTrigger ? circleIcon : circleEmptyIcon).element({
      tag: "span",
      title
    })
  );
  button.classList.toggle("smj-CellTriggerButton--active", isTrigger);
  button.setAttribute("aria-label", title);
  button.title = title;
}

function resolveTriggerButtonContainer(cell: Cell): HTMLElement | null {
  return (
    cell.node.querySelector<HTMLElement>(".jp-cell-toolbar") ??
    cell.node.querySelector<HTMLElement>(".jp-CellHeader, .jp-Cell-header")
  );
}
