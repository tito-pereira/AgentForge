// SPDX-License-Identifier: MPL-2.0
(function (projectRoot) {
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
      return text(projectRow()?.querySelector(".section-heading span")) === "Older schema · v6" &&
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
        valueFor(project, "Storage") === "Current · v7" &&
        valueFor(project, "Work Items") === "0"
      );
    });
    if (!projectShown) return report("fail [project]");

    const objective = document.querySelector("#work-objective");
    const criteria = document.querySelector("#work-criteria");
    const create = objective?.form?.querySelector("button[type=submit]");
    if (!objective || !criteria || !create) return report("fail [work]");
    const workRow = () => Array.from(document.querySelectorAll(".work-tree li")).find(
      (row) => text(row.querySelector("button")) === "Confirm desktop persistence",
    );
    setInput(objective, "Confirm desktop persistence");
    setInput(criteria, "Persist a Work Item through the actual desktop bridge.");
    if (!(await waitFor(() => !create.disabled))) return report("fail [work]");
    objective.form.requestSubmit(create);

    const created = await waitFor(() =>
      text(workRow()?.querySelector("span")) === "TASK · OPEN" &&
      valueFor(document.querySelector(".project-result"), "Work Items") === "1" &&
      !document.querySelector("#work-status")?.disabled &&
      document.querySelector("#work-status"),
    );
    if (!created) return report("fail [work]");
    const status = document.querySelector("#work-status");
    const update = status.form.querySelector("button[type=submit]");
    setInput(status, "ACTIVE");
    if (!(await waitFor(() => !update.disabled))) return report("fail [work]");
    status.form.requestSubmit(update);
    const transitioned = await waitFor(() =>
      text(workRow()?.querySelector("span")) === "TASK · ACTIVE" &&
      valueFor(document.querySelector(".project-result"), "ACTIVE") === "1",
    );
    report(transitioned ? "pass" : "fail [work]");
  }

  void verify().catch(() => report("fail [unexpected]"));
})
