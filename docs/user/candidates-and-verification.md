# Candidates and Exact Verification

## Heuristic candidate

A search lane retains a candidate because it improved a reviewed score or
satisfied a retention rule.

The candidate card may show:

- graph order and edge count;
- graph family and lane provenance;
- heuristic score and witness counts;
- whether counts were capped;
- mutation ancestry for mutation-based lanes, or independent-sample
  reproduction metadata for random restart;
- checkpoint;
- current certification state.

## Heuristic versus exact facts

Keep these visually and conceptually separate:

| Layer | Meaning |
|---|---|
| Heuristic score | Search guidance; may be incomplete or capped |
| Diagnostic | Additional structural analysis |
| Python exact result | One verifier path |
| C++ exact result | Independent verifier path |
| M4 certificate | Authoritative combined result |

A candidate with a low score may still be rejected by M4 with an explicit
cycle.

Random-restart candidates do not claim that the previous random graph was
their parent. Their provenance instead records the lane, source and retaining
checkpoints, seed lineage, absolute evaluation index, generator version,
graph hash and score.

## Candidate pinning

When an accepted action targets a candidate, the system:

1. validates it against the executable candidate registry;
2. creates an immutable candidate snapshot;
3. pins the candidate;
4. prevents pruning while references are active;
5. makes M4 read the immutable snapshot;
6. releases the pin only after all referencing actions/jobs are terminal.

## Stale targets

If a candidate disappears before action acceptance:

- the action is marked `stale_target`;
- it is not executed;
- the Director receives the stale ID and current valid IDs;
- one fresh stateless replan is allowed;
- the entire campaign does not fail on the first stale target.

## Reading an M4 result

A rejection should include:

- verifier status;
- forbidden cycle length;
- explicit witness vertices/edges;
- independent path artifacts;
- manifest and hashes.

A timeout or disagreement remains unknown.

[screenshot: ID=USR-VERIFY-01; save as docs/assets/screenshots/user/verification/candidate-verification.png; crop one candidate detail/card and its M4 verification panel, include the graph visualization, heuristic score with capped/truncated label, Python verifier result, C++ verifier result, final M4 status, and highlighted forbidden cycle witness; exclude other candidate cards.]

## Independent verification command

```bash
sglab verify   --graph6 candidate.graph6   --artifact-dir ./certificate
```

A candidate is `COUNTEREXAMPLE_VERIFIED` only when structural validation and
the required independent exact paths agree.
