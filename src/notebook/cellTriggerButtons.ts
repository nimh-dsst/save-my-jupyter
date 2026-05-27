import type { Cell } from "@jupyterlab/cells";

export function syncCellTriggerDecoration(
  cell: Cell,
  isTrigger: boolean,
): void {
  cell.node.classList.toggle("smj-Cell--trigger", isTrigger);
  if (isTrigger) {
    cell.node.dataset["smjTrigger"] = "true";
    return;
  }

  delete cell.node.dataset["smjTrigger"];
}
