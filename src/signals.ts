export interface ReadableSignal<T> {
  get(): T;
  subscribe(listener: () => void): () => void;
}

export interface WritableSignal<T> extends ReadableSignal<T> {
  set(value: T): void;
  update(updater: (current: T) => T): void;
}

export function createSignal<T>(initialValue: T): WritableSignal<T> {
  let currentValue = initialValue;
  const listeners = new Set<() => void>();

  const notifyListeners = (): void => {
    for (const listener of [...listeners]) {
      listener();
    }
  };

  return {
    get: (): T => currentValue,
    set: (value: T): void => {
      if (Object.is(currentValue, value)) {
        return;
      }

      currentValue = value;
      notifyListeners();
    },
    subscribe: (listener: () => void): (() => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    update: (updater: (current: T) => T): void => {
      const nextValue = updater(currentValue);
      if (Object.is(currentValue, nextValue)) {
        return;
      }

      currentValue = nextValue;
      notifyListeners();
    }
  };
}

export function patchSignal<T extends object>(
  signal: WritableSignal<T>,
  patch: Partial<T>
): void {
  signal.update(current => ({
    ...current,
    ...patch
  }));
}
