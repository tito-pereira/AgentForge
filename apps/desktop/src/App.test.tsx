// SPDX-License-Identifier: MPL-2.0
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { BackendSnapshot, ProjectEntry, ProjectSummary, WorkItem } from "./bridge";

const { invoke, listen } = vi.hoisted(() => ({ invoke: vi.fn(), listen: vi.fn() }));
vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));

const methods = ["projects.list", "project.summary", "project.open", "work.tree", "work.get", "work.create", "work.status"];
const ready: BackendSnapshot = {
  connection: "ready",
  handshake: { protocol_version: 2, version: "0.1.0", methods },
  providers: { providers: [{
    provider: "codex", supported: true, configuration: "default", executable: null,
    observation: "NOT_OBSERVED", capabilities: null,
  }] },
};

const legacy: ProjectEntry = {
  root: "C:\\project", display_name: "Project", last_accessed_at: "2026-01-01T00:00:00Z",
  availability: "AVAILABLE", initialized: true, storage: "LEGACY", schema_version: 6,
};
const missing: ProjectEntry = {
  ...legacy, root: "C:\\missing", display_name: "Missing project", availability: "MISSING",
  initialized: false, storage: "ABSENT", schema_version: null,
};
const summary: ProjectSummary = {
  root: legacy.root, display_name: legacy.display_name, exists: true, is_directory: true,
  initialized: true, storage: "CURRENT", schema_version: 7,
  active_project: { contract_id: "project_contract", revision_id: "project_rev" },
  active_workflow: { contract_id: "workflow_contract", revision_id: "workflow_rev" },
  work_items: { total: 0, by_scope: {}, by_status: {} },
};
const item: WorkItem = {
  work_item_id: "work_1", parent_work_item_id: null, objective: "Handle nested work",
  scope_level: "CHANGE", status: "OPEN", updated_at: "2026-01-02T00:00:00Z",
  allowed_transitions: ["ACTIVE", "BLOCKED", "CANCELLED"],
};

const env = globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean };
let host: HTMLDivElement;
let root: Root;
let lifecycle: (event: { payload: { method: string } }) => void;
let release: ReturnType<typeof vi.fn>;

beforeEach(() => {
  env.IS_REACT_ACT_ENVIRONMENT = true;
  vi.resetAllMocks();
  release = vi.fn();
  listen.mockImplementation(async (_name, callback) => {
    lifecycle = callback;
    return release;
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  env.IS_REACT_ACT_ENVIRONMENT = false;
});

async function render() {
  await act(async () => root.render(<App />));
}

async function click(label: string) {
  const target = Array.from(host.querySelectorAll("button")).find((button) => button.textContent === label);
  if (!target) throw new Error(`Button missing: ${label}`);
  await act(async () => target.click());
}

async function field(id: string, value: string) {
  const target = host.querySelector<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(id);
  if (!target) throw new Error(`Input missing: ${id}`);
  const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(target), "value")?.set;
  await act(async () => {
    setter?.call(target, value);
    target.dispatchEvent(new Event(target instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
  });
}

describe("desktop Home and Projects", () => {
  it("loads known and missing projects passively once the backend negotiates v2", async () => {
    let respond: (value: BackendSnapshot) => void = () => {};
    invoke.mockReturnValueOnce(new Promise<BackendSnapshot>((resolve) => { respond = resolve; }));
    invoke.mockResolvedValueOnce({ projects: [legacy, missing], next_offset: null });
    await render();
    expect(host.textContent).toContain("Connecting");
    await act(async () => respond(ready));
    expect(host.textContent).toContain("0.1.0");
    expect(host.textContent).toContain("v2");
    expect(host.textContent).toContain("Not yet observed");
    expect(host.textContent).toContain("Older schema · v6");
    expect(host.textContent).toContain("Inspect Missing project");
    expect(invoke.mock.calls).toEqual([
      ["backend_snapshot"], ["workspace_request", { method: "projects.list", params: { offset: 0 } }],
    ]);
  });

  it("inspects a missing project without writing recency", async () => {
    invoke.mockResolvedValueOnce(ready)
      .mockResolvedValueOnce({ projects: [missing], next_offset: null })
      .mockResolvedValueOnce({
        ...summary, root: missing.root, display_name: missing.display_name, exists: false,
        is_directory: false, initialized: false, storage: "ABSENT", schema_version: null, work_items: null,
      });
    await render();
    await click("Inspect Missing project");
    expect(host.querySelector(".project-result")?.textContent).toContain("Missing");
    expect(invoke.mock.lastCall).toEqual([
      "workspace_request", { method: "project.summary", params: { root: missing.root } },
    ]);
  });

  it("opens a project, shows canonical tree hierarchy and persists explicit updates via the bridge", async () => {
    let persisted: WorkItem | null = null;
    invoke.mockImplementation(async (command, payload) => {
      if (command === "backend_snapshot") return ready;
      switch (payload.method) {
        case "projects.list": return { projects: [legacy], next_offset: null };
        case "project.open":
        case "project.summary":
          return { ...summary, work_items: persisted ? { total: 2, by_scope: { CHANGE: 1 }, by_status: { [persisted.status]: 1 } } : summary.work_items };
        case "work.tree":
          return { nodes: persisted ? [
            { ...item, work_item_id: "parent", objective: "Parent", depth: 0 },
            { ...persisted, parent_work_item_id: "parent", depth: 1 },
          ] : [], next_offset: null };
        case "work.create": persisted = item; return persisted;
        case "work.status": persisted = { ...item, status: "ACTIVE", allowed_transitions: ["COMPLETED"] }; return persisted;
        default: throw new Error("Unexpected method");
      }
    });
    await render();
    await click("Open Project");
    expect(host.textContent).toContain("Current · v7");
    expect(host.textContent).toContain("project_contract · project_rev");
    expect(host.textContent).toContain("workflow_contract · workflow_rev");
    await field("#work-objective", item.objective);
    await field("#work-scope", "CHANGE");
    await field("#work-criteria", "First criterion\nSecond criterion");
    await click("Create Work Item");
    expect(invoke.mock.calls).toContainEqual(["workspace_request", {
      method: "work.create", params: {
        root: legacy.root, objective: item.objective, scope_level: "CHANGE",
        acceptance_criteria: ["First criterion", "Second criterion"],
      },
    }]);
    expect(host.querySelector('.work-tree li[data-depth="1"]')?.textContent).toContain("CHANGE · OPEN");
    await field("#work-status", "ACTIVE");
    await click("Update status");
    expect(invoke.mock.calls).toContainEqual(["workspace_request", {
      method: "work.status", params: {
        root: legacy.root, work_item_id: item.work_item_id, expected_updated_at: item.updated_at, status: "ACTIVE",
      },
    }]);
    expect(host.querySelector('.work-tree li[data-depth="1"]')?.textContent).toContain("CHANGE · ACTIVE");
  });

  it("shows bounded failures and reconnects on explicit action", async () => {
    invoke.mockRejectedValueOnce("secret bridge detail")
      .mockResolvedValueOnce(ready)
      .mockRejectedValueOnce("secret registry detail");
    await render();
    expect(host.textContent).toContain("could not connect");
    await click("Reconnect");
    expect(host.textContent).toContain("Could not load projects");
    expect(host.textContent).not.toContain("secret");
    expect(invoke.mock.calls.filter(([command]) => command === "restart_backend")).toHaveLength(1);
    await act(async () => root.render(null));
    expect(release).toHaveBeenCalledOnce();
  });

  it("discards in-flight data when the sidecar exits", async () => {
    let respond: (value: ProjectSummary) => void = () => {};
    invoke.mockResolvedValueOnce(ready)
      .mockResolvedValueOnce({ projects: [legacy], next_offset: null })
      .mockReturnValueOnce(new Promise<ProjectSummary>((resolve) => { respond = resolve; }));
    await render();
    await click("Open Project");
    expect(host.textContent).toContain("Opening project");
    await act(async () => lifecycle({ payload: { method: "backend.disconnected" } }));
    await act(async () => respond(summary));
    expect(host.textContent).toContain("Disconnected");
    expect(host.textContent).not.toContain("Current · v7");
  });

  it("keeps controls unavailable when capabilities are absent", async () => {
    invoke.mockResolvedValueOnce({ ...ready, handshake: { ...ready.handshake, methods: ["future.method"] } });
    await render();
    expect(host.textContent).toContain("Project browsing is unavailable");
    expect(host.querySelector<HTMLInputElement>("#project-root")?.disabled).toBe(true);
    expect(invoke.mock.calls).toEqual([["backend_snapshot"]]);
  });
});
