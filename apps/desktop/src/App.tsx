// SPDX-License-Identifier: MPL-2.0
import { useEffect, useRef, useState, type FormEvent } from "react";
import { bridge, type BackendSnapshot, type ProjectStatus, type ProviderStatus } from "./bridge";

const storageLabels: Record<ProjectStatus["storage"], string> = {
  ABSENT: "No database",
  CURRENT: "Current",
  LEGACY: "Older schema",
  INVALID: "Invalid",
  UNVERIFIED: "Unverified",
};

const configurationLabels: Record<ProviderStatus["configuration"], string> = {
  operational: "Project override",
  initial: "Initial project choice",
  global: "User setting",
  default: "Automatic selection",
};

const observationLabels: Record<ProviderStatus["observation"], string> = {
  OBSERVED: "Previously observed",
  NOT_OBSERVED: "Not yet observed",
  UNKNOWN: "Unknown",
};

function Providers({ providers }: { providers: ProviderStatus[] }) {
  return (
    <section aria-labelledby="provider-title">
      <div className="section-heading">
        <h2 id="provider-title">Providers</h2>
        <span>Cached status</span>
      </div>
      {providers.length ? (
        <ul className="providers">
          {providers.map((row) => (
            <li key={row.provider}>
              <div className="provider-heading">
                <h3>{row.provider}</h3>
                <span>{observationLabels[row.observation]}</span>
              </div>
              <p>{row.supported ? configurationLabels[row.configuration] : "Unsupported provider"}</p>
              {row.executable && <code>{row.executable}</code>}
              {row.capabilities && row.observation === "OBSERVED" && (
                <p>
                  {row.capabilities.available ? "Available at last check" : "Unavailable at last check"}
                  {row.capabilities.version && ` · ${row.capabilities.version}`}
                  {row.capabilities.json_events && " · JSON events"}
                  {row.capabilities.stdin_prompt && " · stdin"}
                  {row.capabilities.native_resume && " · Resume"}
                  {row.capabilities.read_only && " · Read-only"}
                </p>
              )}
            </li>
          ))}
        </ul>
      ) : <p>No providers are recorded.</p>}
    </section>
  );
}

export function App() {
  const [snapshot, setSnapshot] = useState<BackendSnapshot | null>(null);
  const [root, setRoot] = useState("");
  const [project, setProject] = useState<ProjectStatus | null>(null);
  const [projectError, setProjectError] = useState("");
  const [checking, setChecking] = useState(false);
  const request = useRef(0);

  function disconnected(error = "The sidecar connection closed.") {
    request.current += 1;
    setSnapshot({ connection: "disconnected", error });
    setProject(null);
    setProjectError("");
    setChecking(false);
  }

  useEffect(() => {
    let mounted = true;
    let unlisten: (() => void) | undefined;
    const current = ++request.current;
    async function connect() {
      try {
        const release = await bridge.onDisconnect(() => {
          if (mounted) disconnected();
        });
        if (!mounted) {
          release();
          return;
        }
        unlisten = release;
        const result = await bridge.snapshot();
        if (mounted && request.current === current) setSnapshot(result);
      } catch {
        if (mounted && request.current === current) disconnected("The desktop bridge could not connect.");
      }
    }
    void connect();
    return () => {
      mounted = false;
      request.current += 1;
      unlisten?.();
    };
  }, []);

  async function reconnect() {
    const current = ++request.current;
    setSnapshot(null);
    try {
      const result = await bridge.restart();
      if (request.current === current) setSnapshot(result);
    } catch {
      if (request.current === current) disconnected("The sidecar could not restart.");
    }
  }

  async function checkProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (snapshot?.connection !== "ready" || !root.trim() || checking) return;
    const current = ++request.current;
    setProject(null);
    setProjectError("");
    setChecking(true);
    try {
      const status = await bridge.project(root);
      if (request.current === current) setProject(status);
    } catch {
      if (request.current === current) setProjectError("The backend could not check this project.");
    } finally {
      if (request.current === current) setChecking(false);
    }
  }

  const ready = snapshot?.connection === "ready";
  const connection = snapshot?.connection ?? "connecting";

  return (
    <main>
      <header className="masthead">
        <div>
          <h1>Corinthos</h1>
          <p>Desktop status</p>
        </div>
        <span className={`connection ${connection}`} role="status">
          {ready ? "Connected" : snapshot ? "Disconnected" : "Connecting…"}
        </span>
      </header>

      <section aria-labelledby="backend-title">
        <div className="section-heading"><h2 id="backend-title">Backend</h2></div>
        {snapshot === null && <p>Waiting for the sidecar handshake.</p>}
        {snapshot?.connection === "disconnected" && (
          <div className="failure">
            <p role="alert">{snapshot.error ?? "The sidecar is disconnected."}</p>
            <button type="button" onClick={() => void reconnect()}>Reconnect</button>
          </div>
        )}
        {ready && (
          <dl className="facts">
            <div><dt>Application version</dt><dd>{snapshot.handshake.version}</dd></div>
            <div><dt>RPC protocol</dt><dd>v{snapshot.handshake.protocol_version}</dd></div>
          </dl>
        )}
      </section>

      <section aria-labelledby="project-title">
        <div className="section-heading"><h2 id="project-title">Project</h2></div>
        <form onSubmit={(event) => void checkProject(event)}>
          <label htmlFor="project-root">Project root</label>
          <div className="field-row">
            <input
              id="project-root"
              value={root}
              onChange={(event) => setRoot(event.target.value)}
              placeholder="Enter a local directory path"
              maxLength={4096}
              disabled={!ready || checking}
              required
            />
            <button type="submit" disabled={!ready || checking || !root.trim()}>
              {checking ? "Checking…" : "Check status"}
            </button>
          </div>
        </form>
        {projectError && <p role="alert">{projectError}</p>}
        {project && (
          <div className="project-result" aria-live="polite">
            <code>{project.root}</code>
            <dl className="facts">
              <div><dt>Path</dt><dd>{project.is_directory ? "Directory" : project.exists ? "Not a directory" : "Missing"}</dd></div>
              <div><dt>Initialized</dt><dd>{project.initialized ? "Yes" : "No"}</dd></div>
              <div><dt>Storage</dt><dd>{storageLabels[project.storage]}{project.schema_version !== null && ` · v${project.schema_version}`}</dd></div>
            </dl>
          </div>
        )}
      </section>

      {ready && <Providers providers={snapshot.providers.providers} />}
    </main>
  );
}
