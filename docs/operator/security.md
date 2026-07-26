# Security

## Default trust boundary

The dashboard binds to `127.0.0.1`. State-changing APIs require a bearer token
when configured.

## Browser input

Browser requests must never supply:

- executable path;
- command line;
- shell string;
- auth source path;
- arbitrary workspace path;
- model tool definition;
- filesystem traversal path.

Worker launch uses a fixed `sys.executable -m sglab ...` argv without
`shell=True`.

## Director input/output

The Director:

- receives a bounded scientific state;
- has no tools;
- has no shell/code/file authority;
- returns a structured reviewed schema;
- can reference only submitted evidence and executable targets;
- cannot certify a counterexample.

## Filesystem

- validate workspace containment;
- use safe relative labels in public reports;
- do not follow symlinks in accounting;
- allow only reviewed App Server wrappers at the exact runtime location with
  trusted executable targets;
- fail unexpected external links as `filesystem_policy`.

## Credentials

- copy only explicitly authorized `auth.json`;
- use private homes and permissions;
- exclude credential material from manifests and reports;
- do not persist credential hashes publicly;
- never put bearer tokens in screenshots.

## Mathematical safety

- heuristic score is never proof;
- timeout is unknown;
- unchecked SAT UNSAT is not certified;
- verifier disagreement is not absence;
- only persisted M4 agreement may stop as certified success.

## Auditability

Preserve:

- plan fingerprint;
- action commit-before-dispatch evidence;
- turn IDs and usage;
- process/lease lifecycle;
- candidate snapshot hashes;
- verifier manifests;
- exact failure domain;
- uncertainty.
