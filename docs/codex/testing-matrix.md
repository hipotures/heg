# Testing Matrix

## Test levels

| Level | Use | Must not do |
|---|---|---|
| Unit | pure validation/projection/accounting | no process/network/model |
| Deterministic integration | real store/state machine with fake Director/App Server | no real auth/model |
| Real-kernel short run | checkpoint/resume/search behavior | no real model unless explicitly authorized |
| Loopback HTTP | API/UI/state controls | no LAN/public exposure |
| Playwright CDP | rendered behavior and accessibility | no paid action unless exact task authorizes |
| Installed App Server no-model | protocol/config/process compatibility | no `turn/start` |
| Authenticated smoke | only when deterministic proof is insufficient | exact authorization required |
| Long soak | resource/recovery behavior | separate budget and acceptance plan |

## Standard gates

```bash
make doctor
make test
make check
make benchmark-smoke
make dashboard-smoke
```

## By subsystem

### Campaign/Resume

- state transition;
- preview has no side effects;
- same campaign/new attempt;
- cumulative/local counters;
- resource change is effective;
- checkpoints and memory reused;
- terminal actions not repeated;
- fault acknowledgement;
- UI state.

### Director

- schema;
- semantic validation;
- evidence/executable registries;
- action ID collision;
- hypothesis operation rules;
- bounded repair prompt;
- one repair only;
- invalid action not executed.

### Candidate/M4

- pin before dispatch;
- deletion/pruning restriction;
- immutable snapshot;
- stale target/replan;
- exact path agreement;
- timeout/disagreement unknown;
- certificate authority.

### Persistence

- previous production schema migration;
- Online Backup;
- integrity/FK;
- historical fingerprints;
- idempotency/transaction boundaries.

### Runtime/App Server

- fake server lifecycle;
- malformed JSONL;
- late abort;
- nullable usage;
- model/effort mismatch;
- skill isolation;
- wrapper policy;
- shutdown/reaping.

### UI/API

- bearer protection;
- state-based controls;
- bounded view model;
- no raw secrets/paths;
- desktop/mobile;
- console/network errors;
- screenshot evidence where requested.

## Real model rule

Do not call a real model to test code that can be proven with a fake/replay
adapter. Real model runs test compatibility and model behavior, not basic
persistence or validation.
