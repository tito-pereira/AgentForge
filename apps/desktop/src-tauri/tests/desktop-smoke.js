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
        valueFor(backend, "RPC protocol") === "v1" &&
        text(codex?.querySelector(".provider-heading span")) === "Not yet observed" &&
        text(codex?.querySelector("p")) === "User setting" &&
        configuredPath &&
        normalizeWindowsPath(configuredPath).endsWith("\\configured\\codex.exe")
      );
    });
    if (!backendReady) return report("fail [backend]");

    const input = document.querySelector("#project-root");
    const form = input?.form;
    const button = form?.querySelector("button[type=submit]");
    if (!(input instanceof HTMLInputElement) || !button || input.disabled) {
      return report("fail [project]");
    }
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    setter.call(input, projectRoot);
    input.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText" }));
    if (!(await waitFor(() => !button.disabled))) return report("fail [project]");
    form.requestSubmit(button);

    const projectShown = await waitFor(() => {
      const project = document.querySelector(".project-result");
      const renderedPath = text(project?.querySelector("code"));
      return (
        renderedPath &&
        normalizeWindowsPath(renderedPath) === normalizeWindowsPath(projectRoot) &&
        valueFor(project, "Path") === "Directory" &&
        valueFor(project, "Initialized") === "Yes" &&
        valueFor(project, "Storage") === "No database"
      );
    });
    report(projectShown ? "pass" : "fail [project]");
  }

  void verify().catch(() => report("fail [unexpected]"));
})
