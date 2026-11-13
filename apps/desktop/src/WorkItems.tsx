// SPDX-License-Identifier: MPL-2.0
import { useEffect, useState, type FormEvent } from "react";
import { bridge, type WorkItem, type WorkNode } from "./bridge";

const scopes = ["TASK", "CHANGE", "PROJECT", "CRITICAL"];

export function WorkItems({ root, methods, onChange }: {
  root: string;
  methods: string[];
  onChange: () => Promise<void>;
}) {
  const [nodes, setNodes] = useState<WorkNode[]>([]);
  const [offset, setOffset] = useState(0);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [item, setItem] = useState<WorkItem | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [objective, setObjective] = useState("");
  const [scope, setScope] = useState("TASK");
  const [criteria, setCriteria] = useState("");
  const [child, setChild] = useState(false);
  const [status, setStatus] = useState("");
  const canCreate = methods.includes("work.create");
  const canPick = methods.includes("work.get");
  const canTransition = methods.includes("work.status");

  async function loadTree(target: number) {
    const result = await bridge.workTree(root, target);
    setNodes(result.nodes);
    setOffset(target);
    setNextOffset(result.next_offset);
  }

  async function run(action: () => Promise<void>, message: string) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch {
      setError(message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    let active = true;
    bridge.workTree(root, 0).then(
      (result) => {
        if (!active) return;
        setNodes(result.nodes);
        setNextOffset(result.next_offset);
        setBusy(false);
      },
      () => {
        if (!active) return;
        setError("Could not load the Work Item tree.");
        setBusy(false);
      },
    );
    return () => { active = false; };
  }, [root]);

  async function pick(id: string) {
    await run(async () => {
      setChild(false);
      setStatus("");
      setItem(await bridge.workGet(root, id));
    }, "Could not load the Work Item.");
  }

  async function refresh(target: number) {
    await run(async () => {
      await loadTree(target);
      if (item) setItem(await bridge.workGet(root, item.work_item_id));
      await onChange();
    }, "Could not refresh the Work Items.");
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const acceptanceCriteria = criteria.split("\n").map((value) => value.trim()).filter(Boolean);
    const cleanObjective = objective.trim();
    if (!canCreate || busy || !cleanObjective) return;
    if (Array.from(cleanObjective).length > 600) {
      setError("Provide an objective of at most 600 characters.");
      return;
    }
    if (acceptanceCriteria.length < 1 || acceptanceCriteria.length > 8 || acceptanceCriteria.some((value) => Array.from(value).length > 300)) {
      setError("Provide 1 to 8 acceptance criteria, at most 300 characters each.");
      return;
    }
    await run(async () => {
      const created = await bridge.workCreate(root, {
        objective: cleanObjective,
        scope_level: scope,
        acceptance_criteria: acceptanceCriteria,
        ...(child && item ? { parent_work_item_id: item.work_item_id } : {}),
      });
      setObjective("");
      setCriteria("");
      setChild(false);
      setStatus("");
      setItem(created);
      await loadTree(0);
      await onChange();
    }, "Could not confirm creation and refresh. Check the Work Item list before retrying.");
  }

  async function transition(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canTransition || busy || !item || !status) return;
    await run(async () => {
      setItem(await bridge.workStatus(root, item, status));
      setStatus("");
      await loadTree(offset);
      await onChange();
    }, "Could not confirm the status change and refresh. Refresh before trying again.");
  }

  const choices = item?.allowed_transitions ?? [];

  return (
    <div className="work-items">
      <div className="section-heading">
        <h3>Work Items</h3>
        <button type="button" onClick={() => void refresh(offset)} disabled={busy}>Refresh Work Items</button>
      </div>
      {busy && <p role="status">Working…</p>}
      {error && <p role="alert">{error}</p>}
      {!busy && !error && nodes.length === 0 && <p>No Work Items on this page.</p>}
      <ol className="work-tree">
        {nodes.map((node) => (
          <li key={node.work_item_id} data-depth={node.depth}>
            {canPick ? (
              <button type="button" disabled={busy} onClick={() => void pick(node.work_item_id)}>{node.objective}</button>
            ) : <strong>{node.objective}</strong>}
            <span>{node.scope_level} · {node.status}{node.depth > 3 ? ` · Level ${node.depth + 1}` : ""}</span>
          </li>
        ))}
      </ol>
      <div className="field-row">
        {offset > 0 && <button disabled={busy} onClick={() => void refresh(0)}>First Work Items</button>}
        {nextOffset !== null && <button disabled={busy} onClick={() => void refresh(nextOffset)}>More Work Items</button>}
      </div>
      {item && (
        <div className="work-selection" aria-live="polite">
          <strong>{item.objective}</strong>
          <p>{item.scope_level} · {item.status}</p>
          {canTransition && choices.length > 0 && (
            <form onSubmit={(event) => void transition(event)}>
              <label htmlFor="work-status">Change status</label>
              <div className="field-row">
                <select id="work-status" value={status} onChange={(event) => setStatus(event.target.value)} required disabled={busy}>
                  <option value="">Choose a status</option>
                  {choices.map((value) => <option key={value}>{value}</option>)}
                </select>
                <button type="submit" disabled={busy || !status}>Update status</button>
              </div>
            </form>
          )}
        </div>
      )}
      {canCreate && (
        <form onSubmit={(event) => void create(event)} className="work-form">
          <h4>Create a Work Item</h4>
          <fieldset disabled={busy}>
            <label htmlFor="work-objective">Objective</label>
            <input id="work-objective" value={objective} onChange={(event) => setObjective(event.target.value)} maxLength={1200} required />
            <label htmlFor="work-scope">Scope</label>
            <select id="work-scope" value={scope} onChange={(event) => setScope(event.target.value)} required>
              {scopes.map((value) => <option key={value}>{value}</option>)}
            </select>
            <label htmlFor="work-criteria">Acceptance criteria, one per line</label>
            <textarea id="work-criteria" value={criteria} onChange={(event) => setCriteria(event.target.value)} maxLength={4807} required />
            {item && (
              <label className="checkbox">
                <input type="checkbox" checked={child} onChange={(event) => setChild(event.target.checked)} /> Add under {item.objective}
              </label>
            )}
            <button type="submit" disabled={!objective.trim() || !criteria.trim()}>Create Work Item</button>
          </fieldset>
        </form>
      )}
    </div>
  );
}
