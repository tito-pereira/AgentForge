# Approved v0.1 architecture decisions

These records transcribe the approved Architecture and Roadmap v0.1 decisions
against the [Phase 0 baseline](../baseline.md). The roadmap gives each decision
its implementation gate. The ADRs establish design and compatibility commitments.

| ID | Decision |
| --- | --- |
| DT-01 | [Keep Python as the domain core](dt-01.md) |
| DT-02 | [Build the desktop GUI with Tauri 2, React and TypeScript](dt-02.md) |
| DT-03 | [Supervise one long-lived Python sidecar](dt-03.md) |
| DT-04 | [Use message-delimited JSON-RPC 2.0 over stdio](dt-04.md) |
| DT-05 | [Keep the Rust Core at the desktop boundary](dt-05.md) |
| DT-06 | [Share one Application API between the GUI and CLI](dt-06.md) |
| DT-07 | [Preserve project-local state and evolve the existing per-user state](dt-07.md) |
| DT-08 | [Keep sqlite3 and incremental migrations](dt-08.md) |
| DT-09 | [Compose Project State as a read model](dt-09.md) |
| DT-10 | [Use Work Item as the universal unit of work](dt-10.md) |
| DT-11 | [Provider-independent Agent Sessions](dt-11.md) |
| DT-12 | [Conservative execution concurrency](dt-12.md) |
| DT-13 | [Deterministic context retrieval first](dt-13.md) |
| DT-14 | [Session Handoff is derived evidence](dt-14.md) |
| DT-15 | [Read-only discovery before external project import](dt-15.md) |
| DT-16 | [Secrets stay outside databases](dt-16.md) |
| DT-17 | [Version the desktop bridge protocol independently](dt-17.md) |
| DT-18 | [Provider telemetry is best-effort](dt-18.md) |
| DT-19 | [Keep source-first installation to one setup command](dt-19.md) |
| DT-20 | [Preserve the platform boundary](dt-20.md) |
