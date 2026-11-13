// SPDX-License-Identifier: MPL-2.0
(function (projectRoot, startSessions) {
  const report = (result) => {
    document.title = "Corinthos desktop smoke: " + result;
  };

  const waitFor = async (predicate) => {
    const deadline = performance.now() + 20_000;
    while (performance.now() < deadline) {
      if (predicate()) return true;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    return false;
  };

  const text = (node) => node?.textContent.trim();
  const valueFor = (container, name) => {
    const label = Array.from(container?.querySelectorAll("dt") ?? []).find(
      (item) => text(item) === name,
    );
    return text(label?.nextElementSibling);
  };

  const normalizeWindowsPath = (path) => path.replaceAll("/", "\\").toLowerCase();

  const setInput = (field, value) => {
    const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(field), "value").set;
    setter.call(field, value);
    field.dispatchEvent(new Event(field instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }));
  };

  async function verify() {
    const backendReady = await waitFor(() => {
      const backend = document.querySelector("#backend-title")?.closest("section");
      const codex = Array.from(document.querySelectorAll(".providers li")).find(
        (row) => text(row.querySelector("h3")) === "codex",
      );
      const configuredPath = text(codex?.querySelector("code"));
      return (
        text(document.querySelector(".connection[role=status]")) === "Connected" &&
        valueFor(backend, "Application version") === "0.1.0" &&
        valueFor(backend, "RPC protocol") === "v2" &&
        text(codex?.querySelector(".provider-heading span")) === "Not yet observed" &&
        text(codex?.querySelector("p")) === "User setting" &&
        configuredPath &&
        normalizeWindowsPath(configuredPath).endsWith("\\configured\\codex.exe")
      );
    });
    if (!backendReady) return report("fail [backend]");

    const projectRow = () => Array.from(document.querySelectorAll(".project-list li")).find((row) => {
      const path = text(row.querySelector("code"));
      return path && normalizeWindowsPath(path) === normalizeWindowsPath(projectRoot);
    });
    const legacyRegistry = await waitFor(() => {
      const missing = Array.from(document.querySelectorAll(".project-list li")).find(
        (row) => text(row.querySelector("h3")) === "missing-project",
      );
      return text(projectRow()?.querySelector(".section-heading span")) === (startSessions ? "Current · v8" : "Older schema · v7") &&
        text(missing?.querySelector(".section-heading span")) === "Missing";
    });
    if (!legacyRegistry) return report("fail [registry]");
    projectRow().querySelector("button").click();

    const projectShown = await waitFor(() => {
      const project = document.querySelector(".project-result");
      const renderedPath = text(project?.querySelector("code"));
      return (
        renderedPath &&
        normalizeWindowsPath(renderedPath) === normalizeWindowsPath(projectRoot) &&
        valueFor(project, "Path") === "Directory" &&
        valueFor(project, "Initialized") === "Yes" &&
        valueFor(project, "Storage") === "Current · v8" &&
        valueFor(project, "Work Items") === "1"
      );
    });
    if (!projectShown) return report("fail [project]");

    const agentsButton = Array.from(document.querySelectorAll(".project-views button")).find(
      (button) => text(button) === "Agents",
    );
    if (!agentsButton) return report("fail [agents]");
    agentsButton.click();
    const passive = await waitFor(() => {
      const view = document.querySelector(".agents");
      const work = view?.querySelector("#session-work-items option");
      return text(view?.querySelector("p")) === "No Agent Sessions on this page." &&
        text(work) === "Preserve this Work Item";
    });
    if (!passive) return report("fail [agents]");
    if (!startSessions) return report("pass");

    const details = () => document.querySelector(".session-detail");
    const state = () => valueFor(details(), "State");
    const startButton = () => document.querySelector(".agents .work-form button[type=submit]");
    const event = (kind) => Array.from(document.querySelectorAll(".session-events li strong")).some(
      (node) => text(node) === kind,
    );

    async function start(timeout) {
      const work = document.querySelector("#session-work-items option");
      setInput(document.querySelector("#session-work"), work.value);
      setInput(document.querySelector("#session-provider"), "codex");
      setInput(document.querySelector("#session-timeout"), String(timeout));
      setInput(document.querySelector("#session-instruction"), "Keep the project unchanged.");
      if (!(await waitFor(() => startButton() && !startButton().disabled))) return false;
      const previous = text(details()?.querySelector("h4"));
      startButton().form.requestSubmit(startButton());
      return waitFor(() => {
        const id = text(details()?.querySelector("h4"));
        return id && id !== previous && state() === "RUNNING" && event("OUTPUT");
      });
    }

    if (!(await start(90))) return report("fail [start]");
    const cancel = Array.from(details().querySelectorAll("button")).find(
      (button) => text(button) === "Cancel session",
    );
    if (!cancel) return report("fail [cancel]");
    cancel.click();
    if (!(await waitFor(() => state() === "CANCELLED" && event("CANCELLED")))) {
      return report("fail [cancel]");
    }
    if (!(await start(8))) return report("fail [start]");
    if (!(await waitFor(() => state() === "TIMED_OUT" && event("TIMED_OUT")))) {
      return report("fail [timeout]");
    }
    if (!(await start(90))) return report("fail [start]");
    report("pass");
  }

  void verify().catch(() => report("fail [unexpected]"));
})
