export const TRIGGER_SNAPSHOT_DEBOUNCE_MS = 5_000;

export interface TriggerDebouncerOptions<
  N,
  R extends { readonly notebook: N },
> {
  readonly debounceMs: number;
  readonly contentKey: (run: R) => MaybePromise<string | null>;
  readonly merge?: (previous: R, next: R) => R;
  readonly onRun: (run: R) => void;
  readonly setTimer?: (callback: () => void, ms: number) => unknown;
  readonly clearTimer?: (timer: unknown) => void;
}

type MaybePromise<T> = T | Promise<T>;

interface PendingRun<R> {
  readonly run: R;
  readonly timer: unknown;
}

/** Per-notebook trailing debounce for repeated automatic trigger snapshots.
 * Manual snapshots bypass this class entirely. */
export class TriggerDebouncer<N, R extends { readonly notebook: N }> {
  private readonly pending = new Map<N, PendingRun<R>>();
  private readonly lastSubmittedContent = new Map<N, string>();
  private readonly submissionChains = new Map<N, Promise<void>>();
  private disposed = false;
  private readonly contentKey: (run: R) => MaybePromise<string | null>;
  private readonly debounceMs: number;
  private readonly merge: (previous: R, next: R) => R;
  private readonly onRun: (run: R) => void;
  private readonly setTimer: (callback: () => void, ms: number) => unknown;
  private readonly clearTimer: (timer: unknown) => void;

  constructor(options: TriggerDebouncerOptions<N, R>) {
    this.contentKey = options.contentKey;
    this.debounceMs = options.debounceMs;
    this.merge = options.merge ?? ((_previous, next) => next);
    this.onRun = options.onRun;
    this.setTimer =
      options.setTimer ??
      ((callback, ms) => {
        return setTimeout(callback, ms);
      });
    this.clearTimer =
      options.clearTimer ??
      ((timer) => {
        clearTimeout(timer as ReturnType<typeof setTimeout>);
      });
  }

  schedule(run: R): void {
    if (this.disposed) {
      return;
    }
    let nextRun = run;
    const existing = this.pending.get(run.notebook);
    if (existing !== undefined) {
      this.clearPending(run.notebook, existing);
      nextRun = this.merge(existing.run, run);
    }

    this.schedulePending(nextRun);
  }

  private schedulePending(run: R): void {
    const timer = this.setTimer(() => {
      this.flush(run.notebook);
    }, this.debounceMs);
    this.pending.set(run.notebook, { run, timer });
  }

  private clearPending(notebook: N, pending: PendingRun<R>): void {
    this.clearTimer(pending.timer);
    this.pending.delete(notebook);
  }

  dispose(): void {
    this.disposed = true;
    for (const pending of this.pending.values()) {
      this.clearTimer(pending.timer);
    }
    this.pending.clear();
  }

  flush(notebook: N): void {
    if (this.disposed) {
      return;
    }
    const pending = this.pending.get(notebook);
    if (pending === undefined) {
      return;
    }
    this.clearPending(notebook, pending);
    this.submitSettled(notebook, pending.run);
  }

  private submitSettled(notebook: N, run: R): void {
    const activeSubmission = this.submissionChains.get(notebook);
    if (activeSubmission !== undefined) {
      const chainedSubmission = activeSubmission.then(
        () => this.resolveAndSubmit(notebook, run),
        () => this.resolveAndSubmit(notebook, run),
      );
      this.trackSubmission(notebook, chainedSubmission);
      return;
    }

    const submission = this.resolveAndSubmit(notebook, run);
    if (isPromiseLike(submission)) {
      this.trackSubmission(notebook, submission);
    }
  }

  private resolveAndSubmit(notebook: N, run: R): MaybePromise<void> {
    let contentKey: MaybePromise<string | null>;
    try {
      contentKey = this.contentKey(run);
    } catch {
      return;
    }

    if (isPromiseLike(contentKey)) {
      return contentKey.then(
        (resolved) => {
          this.submitIfChanged(notebook, run, resolved);
        },
        () => {
          // If content resolution fails, abandon this automatic snapshot.
        },
      );
    }
    this.submitIfChanged(notebook, run, contentKey);
  }

  private trackSubmission(notebook: N, submission: Promise<void>): void {
    const trackedSubmission = submission.catch(() => {
      // Keep later settled trigger candidates from being blocked by this one.
    });
    this.submissionChains.set(notebook, trackedSubmission);
    void trackedSubmission.finally(() => {
      if (this.submissionChains.get(notebook) === trackedSubmission) {
        this.submissionChains.delete(notebook);
      }
    });
  }

  private submitIfChanged(
    notebook: N,
    run: R,
    contentKey: string | null,
  ): void {
    if (this.disposed) {
      return;
    }
    if (contentKey === null) {
      return;
    }
    if (this.lastSubmittedContent.get(notebook) === contentKey) {
      return;
    }
    this.lastSubmittedContent.set(notebook, contentKey);
    this.submit(run);
  }

  private submit(run: R): void {
    this.onRun(run);
  }
}

function isPromiseLike<T>(value: MaybePromise<T>): value is Promise<T> {
  return (
    typeof value === "object" &&
    value !== null &&
    "then" in value &&
    typeof value.then === "function"
  );
}
