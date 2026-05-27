import assert from "node:assert/strict";
import test from "node:test";

import {
  DYNAMIC_KERNEL_METADATA_MARKER,
  collectDynamicKernelMetadata,
  parseDynamicKernelMetadataOutput,
  parseDynamicKernelMetadataPayload,
} from "../src/notebook/kernelMetadata";

void test("dynamic kernel metadata payload keeps only usable smj_tags and smj_run values", () => {
  const metadata = parseDynamicKernelMetadataPayload({
    smj_run: " training-3 ",
    smj_tags: ["baseline", " gpu ", "", 42, "baseline"],
  });

  assert.deepEqual(metadata, {
    runLabel: "training-3",
    tags: ["baseline", "gpu"],
  });
});

void test("dynamic kernel metadata accepts a single string tag and drops blank run labels", () => {
  const metadata = parseDynamicKernelMetadataPayload({
    smj_run: "  ",
    smj_tags: "qc",
  });

  assert.deepEqual(metadata, { runLabel: null, tags: ["qc"] });
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

void test("dynamic kernel metadata collector initializes and reads Python variables", async () => {
  const kernel = new FakeKernel(
    `${DYNAMIC_KERNEL_METADATA_MARKER}{"smj_tags":["qc"],"smj_run":"run-9"}\n`,
  );

  const metadata = await collectDynamicKernelMetadata(kernel);

  assert.deepEqual(metadata, { runLabel: "run-9", tags: ["qc"] });
  assert.equal(kernel.requests.length, 1);
  const request = kernel.requests[0];
  assert.ok(request);
  assert.match(request.code, /smj_tags = \[\]/);
  assert.match(request.code, /smj_run = None/);
  assert.equal(request.store_history, false);
  assert.equal(request.allow_stdin, false);
});

void test("dynamic kernel metadata collector ignores non-Python kernels", async () => {
  const kernel = new FakeKernel(
    `${DYNAMIC_KERNEL_METADATA_MARKER}{"smj_tags":["ignored"],"smj_run":"run"}\n`,
    "ir",
    "R",
  );

  const metadata = await collectDynamicKernelMetadata(kernel);

  assert.deepEqual(metadata, { runLabel: null, tags: [] });
  assert.equal(kernel.requests.length, 0);
});

interface FakeExecuteRequest {
  readonly allow_stdin?: boolean;
  readonly code: string;
  readonly store_history?: boolean;
}

class FakeKernel {
  readonly id = "kernel-1";
  readonly info: Promise<unknown>;
  readonly model: unknown = {};
  readonly requests: FakeExecuteRequest[] = [];
  readonly username = "tester";

  constructor(
    private readonly output: string,
    readonly name = "python3",
    languageName = "python",
  ) {
    this.info = Promise.resolve({ language_info: { name: languageName } });
  }

  requestExecute(content: FakeExecuteRequest): FakeFuture {
    this.requests.push(content);
    const future = new FakeFuture(this.output);
    queueMicrotask(() => {
      future.emitStream();
      future.resolveDone();
    });
    return future;
  }
}

class FakeFuture {
  onIOPub: ((message: unknown) => void) | null = null;
  readonly done: Promise<unknown>;

  private resolve: (value: unknown) => void = () => undefined;

  constructor(private readonly output: string) {
    this.done = new Promise((resolve) => {
      this.resolve = resolve;
    });
  }

  dispose(): void {
    this.resolve(undefined);
  }

  emitStream(): void {
    this.onIOPub?.({
      channel: "iopub",
      content: { name: "stdout", text: this.output },
      header: { msg_type: "stream" },
    });
  }

  resolveDone(): void {
    this.resolve(undefined);
  }
}
