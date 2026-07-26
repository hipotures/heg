# Comparison CLI Reference

The normal comparison workflow is web-driven, but the CLI provides bounded
administrative and worker operations.

## Serve the control plane

```bash
sglab serve   --workspace <comparison-workspace>   --host 127.0.0.1   --port 8788
```

## Worker

```bash
sglab comparisons worker   --workspace <comparison-workspace>   --suite-id <suite-id>
```

Normally the protected Start endpoint launches this fixed argv. Do not launch
a worker for an unauthorized or changed plan.

## Import historical comparison evidence

The implementation supports deterministic import of preserved comparison
reports into read-only suites. Use the installed command help for the exact
subcommand and flags:

```bash
sglab comparisons --help
```

## Import executable campaign fixture

A comparison workspace may import a safe preserved campaign snapshot as an
immutable fixture. The import must exclude auth, private homes, sessions,
rollouts, and wire logs.

## Plan lifecycle

```text
draft → prepared → authorized → running → completed | failed | stopped
```

Authorization binds the exact fingerprint. Changing arm, fixture, order,
limits, schema, or resource policy invalidates it.

## Worker guarantees

- exact arm count/order;
- bounded inference starts;
- inference reservation before model start;
- fresh stateless or explicit persistent sequence;
- no action execution in measurement-only suites;
- no replacement arm after inference;
- durable lease/heartbeat;
- bounded stop and recovery;
- nullable usage.
