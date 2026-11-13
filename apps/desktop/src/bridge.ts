// SPDX-License-Identifier: MPL-2.0
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

export interface ProviderStatus {
  provider: string;
  supported: boolean;
  configuration: "operational" | "initial" | "global" | "default";
  executable: string | null;
  observation: "OBSERVED" | "NOT_OBSERVED" | "UNKNOWN";
  capabilities: {
    available: boolean;
    version: string | null;
    json_events: boolean;
    stdin_prompt: boolean;
    native_resume: boolean;
    read_only: boolean;
  } | null;
}

export interface ProjectStatus {
  root: string;
  exists: boolean;
  is_directory: boolean;
  initialized: boolean;
  storage: "ABSENT" | "CURRENT" | "LEGACY" | "INVALID" | "UNVERIFIED";
  schema_version: number | null;
}

export interface ProjectEntry {
  root: string;
  display_name: string;
  last_accessed_at: string | null;
  availability: "AVAILABLE" | "MISSING" | "UNAVAILABLE";
  initialized: boolean;
  storage: ProjectStatus["storage"];
  schema_version: number | null;
}

export interface ProjectSummary extends ProjectStatus {
  display_name: string;
  active_project: ContractReference | null;
  active_workflow: ContractReference | null;
  work_items: {
    total: number;
    by_status: Record<string, number>;
    by_scope: Record<string, number>;
  } | null;
}

interface ContractReference {
  contract_id: string;
  revision_id: string;
}

export interface WorkItem {
  work_item_id: string;
  parent_work_item_id: string | null;
  objective: string;
  scope_level: string;
  status: string;
  updated_at: string;
  allowed_transitions: string[];
}

export interface WorkNode extends Omit<WorkItem, "updated_at" | "allowed_transitions"> {
  depth: number;
}

interface WorkInput {
  objective: string;
  scope_level: string;
  acceptance_criteria: string[];
  parent_work_item_id?: string;
}

export interface AgentSession {
  session_id: string;
  work_item_id: string;
  project_id: string;
  provider: string;
  provider_version: string | null;
  model: string | null;
  state: string;
  run_generation: number;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cached_tokens: number | null;
  duration_ms: number | null;
  reported_cost: string | null;
  reported_cost_currency: string | null;
  timeout_seconds: number;
  read_only: boolean;
  can_cancel: boolean;
  can_recover: boolean;
  cleanup_unconfirmed: boolean;
}

export interface SessionEvent {
  sequence: number;
  kind: string;
  occurred_at: string;
  payload: Record<string, unknown>;
  native_kind: string | null;
  session_id: string;
}

interface SessionStart {
  provider: string;
  work_item_id: string;
  timeout_seconds: number;
  read_only: boolean;
  instruction?: string;
}

let pending: Promise<unknown> = Promise.resolve();

function request<T>(method: string, params: object) {
  const reply = pending.then(() => invoke<T>("workspace_request", { method, params }));
  pending = reply.catch(() => undefined);
  return reply;
}

export type BackendSnapshot =
  | {
      connection: "ready";
      handshake: { protocol_version: number; version: string; methods: string[] };
      providers: { providers: ProviderStatus[] };
    }
  | { connection: "disconnected"; error?: string };

export const bridge = {
  snapshot: () => invoke<BackendSnapshot>("backend_snapshot"),
  projects: (offset: number) =>
    request<{ projects: ProjectEntry[]; next_offset: number | null }>("projects.list", { offset }),
  project: (root: string, open: boolean) =>
    request<ProjectSummary>(open ? "project.open" : "project.summary", { root }),
  workTree: (root: string, offset: number) =>
    request<{ nodes: WorkNode[]; next_offset: number | null }>("work.tree", { root, offset }),
  workGet: (root: string, work_item_id: string) => request<WorkItem>("work.get", { root, work_item_id }),
  workCreate: (root: string, input: WorkInput) => request<WorkItem>("work.create", { root, ...input }),
  workStatus: (root: string, item: WorkItem, status: string) =>
    request<WorkItem>("work.status", {
      root,
      work_item_id: item.work_item_id,
      expected_updated_at: item.updated_at,
      status,
    }),
  sessions: (root: string, offset: number) =>
    request<{ sessions: AgentSession[]; next_offset: number | null }>("session.list", { root, offset }),
  sessionGet: (root: string, session_id: string) =>
    request<AgentSession>("session.get", { root, session_id }),
  sessionEvents: (root: string, session_id: string, after_sequence: number, limit: number) =>
    request<{ events: SessionEvent[]; next_after_sequence: number }>("session.events", { root, session_id, after_sequence, limit }),
  sessionStart: (root: string, input: SessionStart) =>
    request<AgentSession>("session.start", { root, ...input }),
  sessionCancel: (root: string, session_id: string, generation: number) =>
    request<AgentSession>("session.cancel", { root, session_id, generation }),
  sessionRecover: (root: string, session_id: string, instruction?: string) =>
    request<AgentSession>("session.recover", { root, session_id, ...(instruction ? { instruction } : {}) }),

  restart: () => invoke<BackendSnapshot>("restart_backend"),
  onDisconnect: (handler: () => void) =>
    listen<{ method: string }>("backend-lifecycle", ({ payload }) => {
      if (payload.method === "backend.disconnected" || payload.method === "system.stopping") {
        handler();
      }
    }),
};
