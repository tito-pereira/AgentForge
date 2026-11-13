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

export type BackendSnapshot =
  | {
      connection: "ready";
      handshake: { protocol_version: number; version: string; methods: string[] };
      providers: { providers: ProviderStatus[] };
    }
  | { connection: "disconnected"; error?: string };

export const bridge = {
  snapshot: () => invoke<BackendSnapshot>("backend_snapshot"),
  project: (root: string) => invoke<ProjectStatus>("project_status", { root }),
  restart: () => invoke<BackendSnapshot>("restart_backend"),
  onDisconnect: (handler: () => void) =>
    listen<{ method: string }>("backend-lifecycle", ({ payload }) => {
      if (payload.method === "backend.disconnected" || payload.method === "system.stopping") {
        handler();
      }
    }),
};
