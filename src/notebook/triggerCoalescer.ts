/** Per-notebook accumulation of triggered cells during one run, flushed once
 * when the run completes (contract C-SNAP-08). Pure and notebook-type-agnostic
 * so the coalescing is tested without JupyterLab; ExecutionObserver wires it to
 * NotebookActions. Membership is filtered on trigger-ness only, never success,
 * so errored runs still flush (C-SNAP-07). */
export class TriggerCoalescer<N> {
  private readonly pending = new Map<N, Set<string>>();

  accumulate(notebook: N, cellId: string): void {
    const cells = this.pending.get(notebook) ?? new Set<string>();
    cells.add(cellId);
    this.pending.set(notebook, cells);
  }

  hasPending(notebook: N): boolean {
    return (this.pending.get(notebook)?.size ?? 0) > 0;
  }

  /** Return the run's triggered cells (sorted, de-duplicated) and clear them. */
  flush(notebook: N): readonly string[] {
    const cells = this.pending.get(notebook);
    if (cells === undefined) {
      return [];
    }
    this.pending.delete(notebook);
    return [...cells].sort();
  }
}
