export interface DynamicKernelMetadata {
  readonly runLabel: string | null;
  readonly tags: readonly string[];
}

export interface KernelMetadataKernel {
  readonly info?: Promise<unknown>;
  readonly name: string;
  requestExecute(
    content: KernelMetadataExecuteRequest,
    disposeOnDone?: boolean,
  ): unknown;
}

export interface KernelMetadataExecuteRequest {
  readonly allow_stdin: boolean;
  readonly code: string;
  readonly silent: boolean;
  readonly stop_on_error: boolean;
  readonly store_history: boolean;
}

export interface KernelMetadataFuture {
  onIOPub?: ((message: unknown) => void) | null;
  readonly done: Promise<unknown>;
  dispose?(): void;
}

export const DYNAMIC_KERNEL_METADATA_MARKER =
  "__SAVE_MY_JUPYTER_DYNAMIC_METADATA__";

const EMPTY_DYNAMIC_METADATA: DynamicKernelMetadata = {
  runLabel: null,
  tags: [],
};
const DEFAULT_TIMEOUT_MS = 1500;

const PYTHON_DYNAMIC_METADATA_CODE = `
if "smj_tags" not in globals():
    smj_tags = []
if "smj_run" not in globals():
    smj_run = None

import json as __save_my_jupyter_json

try:
    if isinstance(smj_tags, str):
        __save_my_jupyter_tags = [smj_tags]
    else:
        __save_my_jupyter_tags = [
            __save_my_jupyter_tag
            for __save_my_jupyter_tag in smj_tags
            if isinstance(__save_my_jupyter_tag, str)
        ]
except Exception:
    __save_my_jupyter_tags = []

__save_my_jupyter_run = smj_run if isinstance(smj_run, str) else None
print("${DYNAMIC_KERNEL_METADATA_MARKER}" + __save_my_jupyter_json.dumps({
    "smj_tags": __save_my_jupyter_tags,
    "smj_run": __save_my_jupyter_run,
}))
del __save_my_jupyter_json
del __save_my_jupyter_tags
del __save_my_jupyter_run
`.trim();

export async function collectDynamicKernelMetadata(
  kernel: KernelMetadataKernel | null | undefined,
  options: { readonly timeoutMs?: number } = {},
): Promise<DynamicKernelMetadata> {
  if (kernel == null) {
    return EMPTY_DYNAMIC_METADATA;
  }
  const timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
  if (!(await isPythonKernel(kernel, timeoutMs))) {
    return EMPTY_DYNAMIC_METADATA;
  }

  const stdout: string[] = [];
  let future: KernelMetadataFuture;
  try {
    const candidate = kernel.requestExecute(
      {
        allow_stdin: false,
        code: PYTHON_DYNAMIC_METADATA_CODE,
        silent: false,
        stop_on_error: false,
        store_history: false,
      },
      true,
    );
    if (!isKernelMetadataFuture(candidate)) {
      return EMPTY_DYNAMIC_METADATA;
    }
    future = candidate;
  } catch {
    return EMPTY_DYNAMIC_METADATA;
  }

  future.onIOPub = (message: unknown): void => {
    const text = streamText(message);
    if (text !== null) {
      stdout.push(text);
    }
  };

  try {
    await withTimeout(future.done, timeoutMs);
  } catch {
    future.dispose?.();
    return EMPTY_DYNAMIC_METADATA;
  }

  return parseDynamicKernelMetadataOutput(stdout.join(""));
}

export function parseDynamicKernelMetadataOutput(
  output: string,
): DynamicKernelMetadata {
  const markerIndex = output.lastIndexOf(DYNAMIC_KERNEL_METADATA_MARKER);
  if (markerIndex < 0) {
    return EMPTY_DYNAMIC_METADATA;
  }
  const payloadStart = markerIndex + DYNAMIC_KERNEL_METADATA_MARKER.length;
  const payload = output.slice(payloadStart).split(/\r?\n/, 1)[0] ?? "";
  try {
    return parseDynamicKernelMetadataPayload(JSON.parse(payload));
  } catch {
    return EMPTY_DYNAMIC_METADATA;
  }
}

export function parseDynamicKernelMetadataPayload(
  payload: unknown,
): DynamicKernelMetadata {
  if (typeof payload !== "object" || payload === null) {
    return EMPTY_DYNAMIC_METADATA;
  }
  const record = payload as Record<string, unknown>;
  return {
    runLabel: normalizeRunLabel(record["smj_run"]),
    tags: normalizeTags(record["smj_tags"]),
  };
}

function normalizeTags(value: unknown): string[] {
  const rawTags = typeof value === "string" ? [value] : Array.isArray(value) ? value : [];
  const tags: string[] = [];
  const seen = new Set<string>();
  for (const rawTag of rawTags) {
    if (typeof rawTag !== "string") {
      continue;
    }
    const tag = rawTag.trim();
    if (tag !== "" && !seen.has(tag)) {
      seen.add(tag);
      tags.push(tag);
    }
  }
  return tags;
}

function normalizeRunLabel(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

async function isPythonKernel(
  kernel: KernelMetadataKernel,
  timeoutMs: number,
): Promise<boolean> {
  if (isPythonKernelName(kernel.name)) {
    return true;
  }
  if (kernel.info === undefined) {
    return false;
  }
  try {
    const info = await withTimeout(kernel.info, timeoutMs);
    const languageName = kernelInfoLanguageName(info);
    return languageName === "python";
  } catch {
    return false;
  }
}

function isPythonKernelName(name: string): boolean {
  const normalized = name.toLowerCase();
  return normalized.includes("python") || normalized.includes("ipykernel");
}

function kernelInfoLanguageName(info: unknown): string | null {
  if (typeof info !== "object" || info === null) {
    return null;
  }
  const languageInfo = (info as Record<string, unknown>)["language_info"];
  if (typeof languageInfo !== "object" || languageInfo === null) {
    return null;
  }
  const name = (languageInfo as Record<string, unknown>)["name"];
  return typeof name === "string" ? name.toLowerCase() : null;
}

function streamText(message: unknown): string | null {
  if (typeof message !== "object" || message === null) {
    return null;
  }
  const record = message as Record<string, unknown>;
  if (record["channel"] !== "iopub") {
    return null;
  }
  const header = record["header"];
  if (typeof header !== "object" || header === null) {
    return null;
  }
  if ((header as Record<string, unknown>)["msg_type"] !== "stream") {
    return null;
  }
  const content = record["content"];
  if (typeof content !== "object" || content === null) {
    return null;
  }
  const text = (content as Record<string, unknown>)["text"];
  return typeof text === "string" ? text : null;
}

function isKernelMetadataFuture(value: unknown): value is KernelMetadataFuture {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const done = (value as Record<string, unknown>)["done"];
  return typeof done === "object" && done !== null && "then" in done;
}

function withTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new Error("Timed out while reading dynamic kernel metadata."));
    }, timeoutMs);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (reason: unknown) => {
        clearTimeout(timer);
        reject(reason instanceof Error ? reason : new Error(String(reason)));
      },
    );
  });
}
