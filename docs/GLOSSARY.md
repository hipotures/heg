# Glossary

| Term | Meaning |
|---|---|
| **Workspace** | Isolated filesystem and SQLite environment containing campaigns, artifacts, logs, checkpoints, comparisons, and exports. |
| **Campaign** | One durable scientific experiment with a stable campaign ID. |
| **Execution attempt** | One process-level start or Resume of a campaign, with immutable resources and provenance. |
| **Scientific cycle** | One Director decision cycle followed by any executed actions and measured outcomes. |
| **Director** | Authenticated LLM controller that receives a bounded state and returns reviewed structured actions. |
| **DirectorStateV2** | Bounded, deterministic scientific state submitted to a stateless Director turn. |
| **Scientific memory** | Versioned, bounded projection of durable campaign facts; not conversation-history compression. |
| **Lane** | Long-lived graph-search process with its own parameters, checkpoint lineage, and telemetry. |
| **Micro-batch** | Bounded unit of search work between action and checkpoint boundaries. |
| **Checkpoint** | Hash-verified persisted lane state, including graph and search state needed for recovery. |
| **Candidate** | Retained graph considered scientifically notable or promising. |
| **Candidate pin** | Durable reference that prevents a targeted candidate from being pruned while an action or verification job is active. |
| **Immutable candidate snapshot** | Frozen graph and provenance consumed by verification rather than a later mutable lookup. |
| **M4** | Independent exact-verification boundary. Only M4 may certify a counterexample. |
| **Witness** | Explicit forbidden cycle found by a scorer or verifier. |
| **Witness cap** | Maximum count collected in a bounded heuristic pass; capped counts are approximate or truncated. |
| **Heuristic score** | Search guidance only; never certification. |
| **Exact verifier** | Bounded reference implementation that returns a witness, absence within a complete check, timeout, or error. |
| **Action** | Typed Director request such as starting a lane, scheduling verification, or requesting a diagnostic. |
| **Decision batch** | One validated, durably committed set of Director actions. |
| **Replan** | One fresh stateless correction turn after a bounded validation failure. |
| **Stale target** | Referenced object that is no longer executable when the action is accepted. The action is not executed. |
| **Idempotency key** | Stable key preventing duplicate execution of the same action. |
| **Plan fingerprint** | Canonical hash binding an authorized runtime to exact models, limits, fixtures, and policies. |
| **Comparison suite** | Measurement-only group of model/effort/context arms sharing an immutable fixture. |
| **Stateless turn** | Fresh model thread receiving the complete bounded scientific state. |
| **Persistent thread** | Model thread that retains server-side conversation history across turns. |
| **Compacted thread** | Experimental persistent thread compacted through the App Server protocol. |
| **Fail-closed** | Stop or block execution when required safety, protocol, or integrity conditions are not proven. |
| **Evidence registry** | Exact identifiers visible to and referenceable by the Director. |
| **Advisory target** | Object the Director may discuss but not execute an action against. |
| **Executable target** | Current object that may legally appear in an executable action. |
| **WAL** | SQLite write-ahead log used by workspace databases. |
| **Online Backup** | SQLite API used to obtain a consistent database copy while WAL mode is active. |
