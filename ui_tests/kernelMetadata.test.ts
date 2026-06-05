import assert from "node:assert/strict";
import test from "node:test";

import {
  DYNAMIC_KERNEL_METADATA_MARKER,
  collectDynamicKernelMetadata,
  parseDynamicKernelMetadataOutput,
  parseDynamicKernelMetadataPayload,
  parseDynamicKernelMetadataReply,
} from "../src/notebook/kernelMetadata";

void test("dynamic kernel metadata payload normalizes usable smj_tags and smj_run values", () => {
  const metadata = parseDynamicKernelMetadataPayload({
    smj_run: " training-3 ",
    smj_tags: [
      "baseline",
      " gpu ",
      "",
      42,
      null,
      true,
      { label: "ignored" },
      "baseline",
    ],
  });

  assert.deepEqual(metadata, {
    runLabel: "training-3",
    tags: ["baseline", "gpu", "42", "true"],
  });
});

void test("dynamic kernel metadata accepts a single scalar tag and drops blank run labels", () => {
  const metadata = parseDynamicKernelMetadataPayload({
    smj_run: "  ",
    smj_tags: 2,
  });

  assert.deepEqual(metadata, { runLabel: null, tags: ["2"] });
});

void test("dynamic kernel metadata output parses the marked JSON stream", () => {
  const output = [
    "unrelated stdout",
    `${DYNAMIC_KERNEL_METADATA_MARKER}{"smj_tags":["review"],"smj_run":"run-7"}`,
    "",
  ].join("\n");

  assert.deepEqual(parseDynamicKernelMetadataOutput(output), {
    runLabel: "run-7",
    tags: ["review"],
  });
});

void test("dynamic kernel metadata reply parses user namespace expressions", () => {
  assert.deepEqual(parseDynamicKernelMetadataReply(replyFor(["review"], "run-7")), {
    runLabel: "run-7",
    tags: ["review"],
  });
});

void test("dynamic kernel metadata collector initializes and reads Python variables", async () => {
  const kernel = new FakeKernel(replyFor(["qc"], "run-9"));

  const metadata = await collectDynamicKernelMetadata(kernel);

  assert.deepEqual(metadata, { runLabel: "run-9", tags: ["qc"] });
  assert.equal(kernel.requests.length, 1);
  const request = kernel.requests[0];
  assert.ok(request);
  assert.match(
    request.code,
    /globals\(\)\.pop\("__save_my_jupyter_dynamic_metadata", None\)/,
  );
  assert.match(request.code, /smj_tags = \[\]/);
  assert.match(request.code, /smj_run = None/);
  assert.match(request.code, /str\(__save_my_jupyter_tag\)/);
  assert.match(
    request.user_expressions?.["__save_my_jupyter_dynamic_metadata"] ?? "",
    /globals\(\)\.pop/,
  );
  assert.equal(request.silent, true);
  assert.equal(request.store_history, false);
  assert.equal(request.allow_stdin, false);
});

void test("dynamic kernel metadata collector ignores non-Python kernels", async () => {
  const kernel = new FakeKernel(replyFor(["ignored"], "run"), "ir", "R");

  const metadata = await collectDynamicKernelMetadata(kernel);

  assert.deepEqual(metadata, { runLabel: null, tags: [] });
  assert.equal(kernel.requests.length, 0);
});

interface FakeExecuteRequest {
  readonly allow_stdin?: boolean;
  readonly code: string;
  readonly store_history?: boolean;
  readonly silent?: boolean;
  readonly user_expressions?: Record<string, string>;
}

class FakeKernel {
  readonly id = "kernel-1";
  readonly info: Promise<unknown>;
  readonly model: unknown = {};
  readonly requests: FakeExecuteRequest[] = [];
  readonly username = "tester";

  constructor(
    private readonly reply: unknown,
    readonly name = "python3",
    languageName = "python",
    private readonly delayMs = 0,
  ) {
    this.info = Promise.resolve({ language_info: { name: languageName } });
  }

  requestExecute(content: FakeExecuteRequest): FakeFuture {
    this.requests.push(content);
    const future = new FakeFuture(this.reply);
    const emit = (): void => {
      future.resolveDone();
    };
    if (this.delayMs > 0) {
      setTimeout(emit, this.delayMs);
    } else {
      queueMicrotask(emit);
    }
    return future;
  }
}

class FakeFuture {
  onIOPub: ((message: unknown) => void) | null = null;
  readonly done: Promise<unknown>;

  private resolve: (value: unknown) => void = () => undefined;

  constructor(private readonly reply: unknown) {
    this.done = new Promise((resolve) => {
      this.resolve = resolve;
    });
  }

  dispose(): void {
    this.resolve(undefined);
  }

  resolveDone(): void {
    this.resolve(this.reply);
  }
}

function replyFor(tags: readonly string[], runLabel: string | null): unknown {
  return {
    content: {
      status: "ok",
      user_expressions: {
        __save_my_jupyter_dynamic_metadata: {
          data: {
            "text/plain": `'${toBase64Json({ smj_tags: tags, smj_run: runLabel })}'`,
          },
          status: "ok",
        },
      },
    },
  };
}

function toBase64Json(payload: unknown): string {
  return Buffer.from(JSON.stringify(payload), "utf8").toString("base64");
}
