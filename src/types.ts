import { z } from "zod";

export const snapshotSourceSchema = z.enum(["manual", "trigger_cell"]);

export const commitModeSchema = z.enum(["prompt", "always", "never"]);

export const configLayerSchema = z.enum([
  "request",
  "notebook",
  "user",
  "repo",
  "inferred",
  "fallback",
]);

export const artifactKindSchema = z.enum(["notebook", "figure", "file", "diff"]);

export const jobStateSchema = z.enum([
  "queued",
  "running",
  "persisted",
  "failed",
  "abandoned",
]);

export const runOutcomeSchema = z.enum(["success", "error", "n/a"]);

export const activityRecordSchema = z.object({
  commitHash: z.string().nullable().default(null),
  commitUrl: z.string().nullable().default(null),
  completedAt: z.string().nullable().default(null),
  directoryName: z.string().nullable().default(null),
  directoryUrl: z.string().nullable().default(null),
  displayMessage: z.string(),
  errorCode: z.string().nullable().default(null),
  errorMessage: z.string().nullable().default(null),
  jobId: z.string(),
  metaPageId: z.string().nullable().default(null),
  metaPageName: z.string().nullable().default(null),
  notebookPath: z.string(),
  pageCount: z.number().int().nullable().default(null),
  runOutcome: runOutcomeSchema,
  snapshotId: z.string().nullable().default(null),
  source: snapshotSourceSchema,
  state: jobStateSchema,
  submittedAt: z.string(),
});

export const snapshotJobsResponseSchema = z.object({
  jobs: z.array(activityRecordSchema).default([]),
});

export const notebookExtensionMetadataSchema = z.object({
  all_cells_trigger: z.boolean().default(false),
  default_metadata: z.record(z.string(), z.string()).default({}),
  enabled: z.boolean().default(true),
  labarchives_target_notebook: z.string().nullable().default(null),
  labarchives_target_root_path: z.string().nullable().default(null),
  trigger_cell_ids: z.array(z.string()).default([]),
  watched_paths: z.array(z.string()).default([]),
});

export const cellExtensionMetadataSchema = z.object({
  trigger: z.boolean().default(false),
});

export const snapshotUserMetadataSchema = z.object({
  experiment_context: z.string().nullable().default(null),
  extra_fields: z.record(z.string(), z.string()).default({}),
  notes: z.string().nullable().default(null),
  run_label: z.string().nullable().default(null),
  tags: z.array(z.string()).default([]),
});

export const notebookContextSchema = z.object({
  cell_execution_count: z.number().int().nullable().default(null),
  cell_ids: z.array(z.string()).default([]),
  document_id: z.string().nullable().default(null),
  kernel_id: z.string().nullable().default(null),
  notebook_name: z.string(),
  notebook_path: z.string(),
  triggering_cell_id: z.string().nullable().default(null),
});

export const manualSnapshotRequestSchema = z.object({
  client_timestamp: z.string().optional(),
  commit_mode: commitModeSchema,
  notebook_context: notebookContextSchema,
  source: z.literal("manual"),
  user_metadata: snapshotUserMetadataSchema,
});

export const triggerSnapshotRequestSchema = z.object({
  client_timestamp: z.string().optional(),
  commit_mode: commitModeSchema,
  notebook_context: notebookContextSchema,
  source: z.literal("trigger_cell"),
  user_metadata: snapshotUserMetadataSchema,
});

export const snapshotRequestPayloadSchema = z.discriminatedUnion("source", [
  manualSnapshotRequestSchema,
  triggerSnapshotRequestSchema,
]);

export const repoStateSchema = z.object({
  headCommit: z.string().nullable(),
  isDirty: z.boolean(),
  relativeNotebookPath: z.string().nullable(),
  remoteUrl: z.string().nullable(),
  repoRoot: z.string().nullable(),
});

export const authStateSchema = z.object({
  pendingRequestId: z.string().nullable().default(null),
  status: z.enum(["authenticated", "pending", "unauthenticated"]),
  storedNotebookNames: z.array(z.string()).default([]),
  storedUserEmail: z.string().nullable().default(null),
  userEmail: z.string().nullable().default(null),
});

export const labArchivesTargetSchema = z.object({
  notebookName: z.string(),
  rootPath: z.string(),
});

export const plannedArtifactSchema = z.object({
  kind: artifactKindSchema,
  summary: z.string(),
});

export const snapshotPreviewResponseSchema = z.object({
  artifacts: z.array(plannedArtifactSchema).default([]),
  generatedAt: z.string(),
  provenance: z.record(z.string(), configLayerSchema).default({}),
  runLabel: z.string().nullable().default(null),
  source: z.enum(["frontend", "disk"]),
  tags: z.array(z.string()).default([]),
  target: labArchivesTargetSchema,
});

export const effectiveConfigSchema = z.object({
  allCellsTrigger: z.boolean(),
  commitMessageTemplate: z.string(),
  commitMode: commitModeSchema,
  includeDiffWhenDirty: z.boolean(),
  includeNotebookFile: z.boolean(),
  metadataTemplate: z.record(z.string(), z.string()).default({}),
  stageNotebookOnCommit: z.boolean(),
  stageWatchedPathsOnCommit: z.boolean(),
  target: labArchivesTargetSchema,
  watchedPaths: z.array(z.string()).default([]),
});

export const effectiveStateSchema = z.object({
  auth: authStateSchema,
  effectiveConfig: effectiveConfigSchema.nullable(),
  notebookMetadata: notebookExtensionMetadataSchema.nullable(),
  repo: repoStateSchema.nullable(),
  repoConfigPath: z.string().nullable(),
  repoConfigLoaded: z.boolean(),
});

export const authStartResponseSchema = z.object({
  authUrl: z.string().nullable(),
  message: z.string(),
  requestId: z.string().nullable(),
  status: z.string(),
});

export const configInitResponseSchema = z.object({
  configPath: z.string(),
  rootDirectory: z.string(),
  status: z.enum(["created", "exists"]),
});

export const watchSyncResponseSchema = z.object({
  registeredWatchPaths: z.array(z.string()),
  status: z.enum(["registered", "unregistered"]),
});

export const snapshotSubmissionResultSchema = z.discriminatedUnion("status", [
  z.object({
    commitCreated: z.boolean().default(false),
    commitHash: z.string().nullable().default(null),
    commitUrl: z.string().nullable().default(null),
    jobId: z.string(),
    labarchivesDirectoryName: z.string().nullable().default(null),
    labarchivesMetaPageId: z.string().nullable().default(null),
    labarchivesMetaPageName: z.string().nullable().default(null),
    labarchivesPageCount: z.number().int().nullable().default(null),
    labarchivesPageId: z.string().nullable().default(null),
    labarchivesPageName: z.string().nullable().default(null),
    queuePosition: z.number(),
    snapshotId: z.string().nullable().default(null),
    status: z.literal("accepted"),
  }),
  z.object({
    message: z.string(),
    reasonCode: z.string(),
    status: z.literal("rejected"),
  }),
]);

export const userPreferencesSchema = z.object({
  defaultCommitMode: commitModeSchema.default("prompt"),
  defaultRunLabel: z.string().nullable().default(null),
  defaultTags: z.array(z.string()).default([]),
  rememberCommitChoice: z.boolean().default(false),
});

export const apiErrorSchema = z.object({
  error: z.object({
    code: z.string(),
    context: z.record(z.string(), z.string()).default({}),
    message: z.string(),
  }),
});

export type ActivityRecord = z.infer<typeof activityRecordSchema>;
export type ApiError = z.infer<typeof apiErrorSchema>;
export type ArtifactKind = z.infer<typeof artifactKindSchema>;
export type JobState = z.infer<typeof jobStateSchema>;
export type RunOutcome = z.infer<typeof runOutcomeSchema>;
export type SnapshotJobsResponse = z.infer<typeof snapshotJobsResponseSchema>;
export type AuthStartResponse = z.infer<typeof authStartResponseSchema>;
export type AuthState = z.infer<typeof authStateSchema>;
export type CellExtensionMetadata = z.infer<typeof cellExtensionMetadataSchema>;
export type CommitMode = z.infer<typeof commitModeSchema>;
export type ConfigLayer = z.infer<typeof configLayerSchema>;
export type PlannedArtifact = z.infer<typeof plannedArtifactSchema>;
export type SnapshotPreviewResponse = z.infer<
  typeof snapshotPreviewResponseSchema
>;
export type ConfigInitResponse = z.infer<typeof configInitResponseSchema>;
export type EffectiveConfig = z.infer<typeof effectiveConfigSchema>;
export type EffectiveState = z.infer<typeof effectiveStateSchema>;
export type NotebookContext = z.infer<typeof notebookContextSchema>;
export type NotebookExtensionMetadata = z.infer<
  typeof notebookExtensionMetadataSchema
>;
export type SnapshotRequestPayload = z.infer<
  typeof snapshotRequestPayloadSchema
>;
export type SnapshotSubmissionResult = z.infer<
  typeof snapshotSubmissionResultSchema
>;
export type SnapshotUserMetadata = z.infer<typeof snapshotUserMetadataSchema>;
export type UserPreferences = z.infer<typeof userPreferencesSchema>;
export type WatchSyncResponse = z.infer<typeof watchSyncResponseSchema>;

export function parseApiError(raw: unknown): ApiError {
  return apiErrorSchema.parse(raw);
}

export function parseAuthStartResponse(raw: unknown): AuthStartResponse {
  return authStartResponseSchema.parse(raw);
}

export function parseAuthState(raw: unknown): AuthState {
  return authStateSchema.parse(raw);
}

export function parseConfigInitResponse(raw: unknown): ConfigInitResponse {
  return configInitResponseSchema.parse(raw);
}

export function parseCellExtensionMetadata(
  raw: unknown,
): CellExtensionMetadata {
  return cellExtensionMetadataSchema.parse(raw);
}

export function parseEffectiveState(raw: unknown): EffectiveState {
  return effectiveStateSchema.parse(raw);
}

export function parseNotebookExtensionMetadata(
  raw: unknown,
): NotebookExtensionMetadata {
  return notebookExtensionMetadataSchema.parse(raw);
}

export function parseSnapshotRequestPayload(
  raw: unknown,
): SnapshotRequestPayload {
  return snapshotRequestPayloadSchema.parse(raw);
}

export function parseSnapshotPreviewResponse(
  raw: unknown,
): SnapshotPreviewResponse {
  return snapshotPreviewResponseSchema.parse(raw);
}

export function parseSnapshotJobsResponse(raw: unknown): SnapshotJobsResponse {
  return snapshotJobsResponseSchema.parse(raw);
}

export function parseActivityRecord(raw: unknown): ActivityRecord {
  return activityRecordSchema.parse(raw);
}

export function parseSnapshotSubmissionResult(
  raw: unknown,
): SnapshotSubmissionResult {
  return snapshotSubmissionResultSchema.parse(raw);
}

export function parseUserPreferences(raw: unknown): UserPreferences {
  return userPreferencesSchema.parse(raw);
}

export function parseWatchSyncResponse(raw: unknown): WatchSyncResponse {
  return watchSyncResponseSchema.parse(raw);
}
