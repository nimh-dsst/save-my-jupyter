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
  readonly user_expressions?: Record<string, string>;
}

export interface KernelMetadataFuture {
  onIOPub?: ((message: unknown) => void) | null;
  readonly done: Promise<unknown>;
  dispose?(): void;
}

export const DYNAMIC_KERNEL_METADATA_MARKER =
  "__SAVE_MY_JUPYTER_DYNAMIC_METADATA__";

const DYNAMIC_KERNEL_METADATA_EXPRESSION = "__save_my_jupyter_dynamic_metadata";
const EMPTY_DYNAMIC_METADATA: DynamicKernelMetadata = {
  runLabel: null,
  tags: [],
};
const DEFAULT_TIMEOUT_MS = 1500;

const PYTHON_DYNAMIC_METADATA_CODE = `
globals().pop("__save_my_jupyter_dynamic_metadata", None)
if "smj_tags" not in globals():
    smj_tags = []
if "smj_run" not in globals():
    smj_run = None

import base64 as __save_my_jupyter_base64
import json as __save_my_jupyter_json

try:
    if smj_tags is None:
        __save_my_jupyter_tags = []
    elif isinstance(smj_tags, str):
        __save_my_jupyter_tags = [smj_tags]
    else:
        try:
            __save_my_jupyter_iterator = iter(smj_tags)
        except TypeError:
            __save_my_jupyter_tags = [str(smj_tags)]
        else:
            __save_my_jupyter_tags = [
                str(__save_my_jupyter_tag)
                for __save_my_jupyter_tag in __save_my_jupyter_iterator
                if __save_my_jupyter_tag is not None
            ]
except Exception:
    __save_my_jupyter_tags = []

__save_my_jupyter_run = smj_run if isinstance(smj_run, str) else None
__save_my_jupyter_dynamic_metadata = __save_my_jupyter_base64.b64encode(
    __save_my_jupyter_json.dumps({
    "smj_tags": __save_my_jupyter_tags,
    "smj_run": __save_my_jupyter_run,
    }).encode("utf-8")
).decode("ascii")
del __save_my_jupyter_base64
del __save_my_jupyter_json
del __save_my_jupyter_tags
del __save_my_jupyter_run
globals().pop("__save_my_jupyter_iterator", None)
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

  let future: KernelMetadataFuture;
  try {
    const candidate = kernel.requestExecute(
      {
        allow_stdin: false,
        code: PYTHON_DYNAMIC_METADATA_CODE,
        silent: true,
        stop_on_error: false,
        store_history: false,
        user_expressions: {
          [DYNAMIC_KERNEL_METADATA_EXPRESSION]: `(${DYNAMIC_KERNEL_METADATA_EXPRESSION}, globals().pop("${DYNAMIC_KERNEL_METADATA_EXPRESSION}", None))[0]`,
        },
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

  try {
    const reply = await withTimeout(future.done, timeoutMs);
    const metadata = parseDynamicKernelMetadataReply(reply);
    if (metadata !== EMPTY_DYNAMIC_METADATA) {
      return metadata;
    }
  } catch {
    future.dispose?.();
    return EMPTY_DYNAMIC_METADATA;
  }

  return EMPTY_DYNAMIC_METADATA;
}

export function parseDynamicKernelMetadataReply(
  reply: unknown,
): DynamicKernelMetadata {
  const content = asRecord(asRecord(reply)?.["content"]);
  if (content?.["status"] !== "ok") {
    return EMPTY_DYNAMIC_METADATA;
  }
  const userExpressions = asRecord(content["user_expressions"]);
  const expression = asRecord(
    userExpressions?.[DYNAMIC_KERNEL_METADATA_EXPRESSION],
  );
  if (expression?.["status"] !== "ok") {
    return EMPTY_DYNAMIC_METADATA;
  }
  const data = asRecord(expression["data"]);
  const jsonData = data?.["application/json"];
  if (typeof jsonData === "string") {
    return parseEncodedDynamicKernelMetadata(jsonData);
  }
  const textData = data?.["text/plain"];
  if (typeof textData === "string") {
    return parseEncodedDynamicKernelMetadata(stripPythonStringLiteral(textData));
  }
  return EMPTY_DYNAMIC_METADATA;
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
  const rawTags = Array.isArray(value)
    ? value
    : value === null || value === undefined
      ? []
      : [value];
  const tags: string[] = [];
  const seen = new Set<string>();
  for (const rawTag of rawTags) {
    const tag = normalizeTag(rawTag);
    if (tag === null || seen.has(tag)) {
      continue;
    }
    seen.add(tag);
    tags.push(tag);
  }
  return tags;
}

function normalizeTag(value: unknown): string | null {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed === "" ? null : trimmed;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    const trimmed = String(value).trim();
    return trimmed === "" ? null : trimmed;
  }
  return null;
}

function normalizeRunLabel(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function parseEncodedDynamicKernelMetadata(
  encoded: string,
): DynamicKernelMetadata {
  const decoded = decodeBase64Utf8(encoded.trim());
  if (decoded === null) {
    return EMPTY_DYNAMIC_METADATA;
  }
  try {
    return parseDynamicKernelMetadataPayload(JSON.parse(decoded));
  } catch {
    return EMPTY_DYNAMIC_METADATA;
  }
}

function decodeBase64Utf8(encoded: string): string | null {
  try {
    const binary = globalThis.atob(encoded);
    const bytes = Uint8Array.from(binary, (char) => char.charCodeAt(0));
    return new TextDecoder().decode(bytes);
  } catch {
    return null;
  }
}

function stripPythonStringLiteral(value: string): string {
  const trimmed = value.trim();
  if (
    (trimmed.startsWith("'") && trimmed.endsWith("'")) ||
    (trimmed.startsWith('"') && trimmed.endsWith('"'))
  ) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
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

function isKernelMetadataFuture(value: unknown): value is KernelMetadataFuture {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const done = (value as Record<string, unknown>)["done"];
  return typeof done === "object" && done !== null && "then" in done;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
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
