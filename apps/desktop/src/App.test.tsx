// SPDX-License-Identifier: MPL-2.0
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import type { BackendSnapshot, ProjectStatus } from "./bridge";

const { invoke, listen } = vi.hoisted(() => ({
  invoke: vi.fn(),
  listen: vi.fn(),
}));

vi.mock("@tauri-apps/api/core", () => ({ invoke }));
vi.mock("@tauri-apps/api/event", () => ({ listen }));

const ready: BackendSnapshot = {
  connection: "ready",
  handshake: { protocol_version: 1, version: "0.1.0", methods: ["project.status"] },
  providers: {
    providers: [{
      provider: "codex",
      supported: true,
      configuration: "default",
      executable: null,
      observation: "NOT_OBSERVED",
      capabilities: null,
    }],
  },
};

const actEnvironment = globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean };
let host: HTMLDivElement;
let root: Root;
let lifecycle: (event: { payload: { method: string } }) => void;
let release: ReturnType<typeof vi.fn>;

beforeEach(() => {
  actEnvironment.IS_REACT_ACT_ENVIRONMENT = true;
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
  actEnvironment.IS_REACT_ACT_ENVIRONMENT = false;
});

async function render(node: ReactNode = <App />) {
  await act(async () => root.render(node));
}

async function submitProject(path: string) {
  const input = host.querySelector<HTMLInputElement>("#project-root");
  if (!input) throw new Error("Missing project path input.");
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  await act(async () => {
    setter?.call(input, path);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => {
    host.querySelector("form")?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  });
}

describe("desktop status", () => {
  it("shows loading then real backend values using a passive snapshot only", async () => {
    let respond: (value: BackendSnapshot) => void = () => {};
    invoke.mockReturnValue(new Promise<BackendSnapshot>((resolve) => { respond = resolve; }));
    await render();
    expect(host.textContent).toContain("Connecting");
    expect(host.querySelector("input")?.disabled).toBe(true);
    await act(async () => respond(ready));
    expect(host.textContent).toContain("Connected");
    expect(host.textContent).toContain("0.1.0");
    expect(host.textContent).toContain("v1");
    expect(host.textContent).toContain("codex");
    expect(host.textContent).toContain("Not yet observed");
    expect(host.textContent).not.toContain("Unavailable");
    expect(invoke.mock.calls).toEqual([["backend_snapshot"]]);
  });

  it("shows project status only after an explicit submission", async () => {
    invoke.mockResolvedValueOnce(ready).mockResolvedValueOnce({
      root: "C:\\project",
      exists: true,
      is_directory: true,
      initialized: true,
      storage: "CURRENT",
      schema_version: 6,
    });
    await render();
    await submitProject("C:\\project");
    expect(invoke.mock.calls).toEqual([["backend_snapshot"], ["project_status", { root: "C:\\project" }]]);
    expect(host.textContent).toContain("Current · v6");
    expect(host.textContent).toContain("C:\\project");
  });

  it("handles disconnect events and restarts only after a click", async () => {
    invoke.mockResolvedValueOnce(ready).mockResolvedValueOnce(ready);
    await render();
    await act(async () => lifecycle({ payload: { method: "backend.disconnected" } }));
    expect(host.textContent).toContain("Disconnected");
    expect(host.querySelector("input")?.disabled).toBe(true);
    expect(invoke.mock.calls).toEqual([["backend_snapshot"]]);
    await act(async () => host.querySelector<HTMLButtonElement>("button[type=button]")?.click());
    expect(invoke.mock.calls).toEqual([["backend_snapshot"], ["restart_backend"]]);
    expect(host.textContent).toContain("Connected");
    await act(async () => root.render(null));
    expect(release).toHaveBeenCalledOnce();
  });

  it("shows bounded connection and project failures", async () => {
    invoke.mockRejectedValueOnce("untrusted details").mockResolvedValueOnce(ready).mockRejectedValueOnce("secret");
    await render();
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("could not connect");
    expect(host.textContent).not.toContain("untrusted details");
    await act(async () => host.querySelector<HTMLButtonElement>("button[type=button]")?.click());
    await submitProject("C:\\missing");
    expect(host.querySelector('[role="alert"]')?.textContent).toContain("could not check this project");
    expect(host.textContent).not.toContain("secret");
  });

  it("discards an in-flight project result if the sidecar exits", async () => {
    let respond: (value: ProjectStatus) => void = () => {};
    invoke.mockResolvedValueOnce(ready).mockReturnValueOnce(
      new Promise<ProjectStatus>((resolve) => { respond = resolve; }),
    );
    await render();
    await submitProject("C:\\project");
    expect(host.textContent).toContain("Checking");
    await act(async () => lifecycle({ payload: { method: "backend.disconnected" } }));
    await act(async () => respond({
      root: "C:\\project",
      exists: true,
      is_directory: true,
      initialized: true,
      storage: "CURRENT",
      schema_version: 6,
    }));
    expect(host.textContent).toContain("Disconnected");
    expect(host.textContent).not.toContain("Current · v6");
  });
});
