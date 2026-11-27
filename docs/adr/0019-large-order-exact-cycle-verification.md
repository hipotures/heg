# ADR 0019: Large-Order Exact Cycle Verification (`128 < n <= 512`)

- **Status:** Accepted
- **Date:** 2026-11-27

## Context

[ADR 0004](0004-m4-certification-authority.md) establishes the C++17 M4 verifier
(`cpp/sglab_cyclecheck.cpp`, built as `_build/sglab-cyclecheck`) as the sole
certification authority for campaign counterexamples. That implementation uses
128-bit bitmasks (`__uint128_t`) and therefore supports graphs of order
`n <= 128`.

Extremal upper-bound constructions for $f(5)$ (graphs avoiding
$\{C_4, C_8, C_{16}, C_{32}\}$) require verifying sparse graphs of order
`n = 300..512` (e.g., `n = 370` cubic and `n = 345` $\delta \ge 3$). Running
M4 directly on `n > 128` is impossible without changing M4's fixed 128-bit
representation, and weakening M4's audited `n <= 128` campaign boundary is
undesirable.

## Decision

1. **Preserve M4 (`n <= 128`) unchanged** as the sole certification authority
   for campaign counterexamples and all `n <= 128` witnesses (including
   $f_{\delta \ge 3}(4) \le 73$ and $f_{\delta \ge 3}(4) \le 77$).
2. **Introduce a separate dual-verifier path for `128 < n <= 512`** consisting
   of two algorithmically independent exact implementations:
   - **Rust `sglab-rust-engine verify-large`** (`rust/sglab-engine/src/large_verify.rs`):
     16-core canonical-start Meet-in-the-Middle using `[u64; 8]` (512-bit)
     masks, strict CLI/graph6 validation, and release-mode runtime witness
     verification (`verify_witness_runtime`).
   - **Independent C++17 DFS verifier** (`tools/extremal/sglab_cyclecheck_large.cpp`):
     canonical-start DFS with sound BFS distance pruning on `std::array<uint64_t, 8>`.
3. **Never conflate the two authorities in reports**: certificates at
   `n <= 128` require M4; certificates at `128 < n <= 512` require agreement of
   both `verify-large` and `sglab-cyclecheck-large` (and may additionally be
   cross-checked by third-party verifiers such as `cyc.c`), and must explicitly
   state that they were certified by the large-order dual-verifier path rather
   than M4.

## Consequences

- Existing `n <= 128` M4 invariants, hashes, and campaign runtime behavior are
  completely untouched.
- Extremal constructions up to `n = 512` can be verified deterministically in
  milliseconds without trusting a single implementation.
- Probabilistic detectors (such as Monte Carlo `bjorklund-c32`) remain strictly
  excluded from certifying cycle absence at any order.

## Rejected alternatives

- Widening `cpp/sglab_cyclecheck.cpp` to 512 bits globally (unnecessary risk
  and performance regression on the audited `n <= 128` campaign hot path).
- Trusting a single `n > 128` verifier or analytic window calculus alone
  without full-graph verification.
