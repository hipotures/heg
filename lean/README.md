# Sglab Lean 4 Formalization (`lean/`)

Pure Lean 4 (`v4.36.0`) kernel-checked formalization of our main theoretical and
extremal graph-theoretic results on `{C4, C8, ..., C_{2^k}}`-free graphs — with
**zero external dependencies** (no Mathlib), **zero `sorry`**, **zero custom axioms**,
and **zero `native_decide`** (every finite verification runs inside the Lean 4 kernel).

## Modules

| Module | Contents |
|---|---|
| `Sglab/Graph.lean` | Finite simple graphs (`FinGraph n`), `SimplePath`, `SimpleCycle`, BFS distance potential lower bound (`dist_lower_of_potential`), provably sound canonical bitmask cycle DFS (`not_hasCycle_of_dfs`), and provably sound weighted short-cycle DFS (`weighted_cycle_lower_of_check`). |
| `Sglab/GadgetLift.lean` | General 3-port vertex-replacement lift (`liftGraph`), degree preservation (`liftGraph_minDeg3`, `liftGraph_isCubic`), and the **Master 3-Port Cycle Projection & Length Lower Bound Theorem** (`liftGraph_cycle_dichotomy`, `liftGraph_no_cycle`). |
| `Sglab/Gadgets.lean` | Kernel-verified gadgets `H7` (`n=7`, cubic-internal, port distances `(2,2,3)`), `H8star` (`n=8`, `δ≥3`, port distances `(3,3,2)`), and `H15` (`n=15`, cubic-internal, port distances `(3,3,5)`): `{C4, C8}`-freeness via `not_hasCycle_of_dfs`, port distances via explicit BFS potentials. |
| `Sglab/Records.lean` | Kernel-checked extremal upper bounds: `f_delta3_4_le_73` (`3·H_8* + 7·H_7`), `f_delta3_4_le_73_alt` (`1·U_1 + 9·H_8*`), `f_cubic_5_le_370` (`20·H_15 + 10·H_7`), `f_delta3_5_le_345` (`15·H_15 + 15·H_8*`), and the general 4-packing theorem `f_cubic_6_4packing` (`≤ 30,360` for any `N = 2048` cubic girth-`≥ 17` base, `f_cubic_6_4packing_N2048`). |
| `Sglab/TutteCoxeterLowerBound.lean` | Kernel-checked verification of all 90 8-cycles of the Tutte–Coxeter graph, exact 8-fold incidence of every `(v, off_port)` pair (`tc_incidence_eq_8`), the exact double-counting identity (`tc_double_counting_eq`), `8 a_15 - 4 b_8 - 8 c_7 ≥ 45` (`tc_double_counting_bound`), `a_15 ≥ 18` cubic / `a_15 ≥ 14` general / `c_7 ≤ 3` at `a_15 = 15`, and formal soundness of the SAT/DRAT `--add-slack-bound` cardinality constraint (`tc_slack_card_sound`, `tc_slack_card_n354_cubic`, `tc_slack_card_n338_delta3`). |

## Building and Auditing Axioms

```bash
cd lean
lake build
```

To verify that every headline theorem uses only standard Lean foundational axioms
(`propext`, `Classical.choice`, `Quot.sound`) — with zero `sorryAx` and zero `Lean.ofReduceBool`:

```bash
cd lean
lake env lean --stdin << 'EOF'
import Sglab
#print axioms Sglab.liftGraph_cycle_dichotomy
#print axioms Sglab.f_delta3_4_le_73
#print axioms Sglab.f_delta3_4_le_73_alt
#print axioms Sglab.f_cubic_5_le_370
#print axioms Sglab.f_delta3_5_le_345
#print axioms Sglab.f_cubic_6_4packing
#print axioms Sglab.f_cubic_6_4packing_N2048
#print axioms Sglab.tc_double_counting_eq
#print axioms Sglab.tc_double_counting_bound
#print axioms Sglab.tc_cubic_a15_ge_18
#print axioms Sglab.tc_delta3_a15_ge_14
#print axioms Sglab.tc_delta3_a15_15_c7_le_3
#print axioms Sglab.tc_slack_card_sound
#print axioms Sglab.tc_slack_card_n354_cubic
#print axioms Sglab.tc_slack_card_n338_delta3
EOF
```
