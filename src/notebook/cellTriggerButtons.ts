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
  const header = cell.node.querySelector<HTMLElement>(".jp-CellHeader, .jp-Cell-header");
  if (header === null) {
    return;
  }

  header.classList.add("smj-CellHeader");
  let button = header.querySelector<HTMLButtonElement>(".smj-CellTriggerButton");
  if (button === null) {
    button = document.createElement("button");
    button.className = "jp-Button jp-mod-minimal smj-CellTriggerButton";
    button.type = "button";
    button.addEventListener("click", event => {
      event.preventDefault();
      event.stopPropagation();
      onToggle(cell);
    });
    header.appendChild(button);
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
