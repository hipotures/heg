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
| `Sglab/TutteCoxeterLowerBound.lean` | Kernel-checked verification of all 90 8-cycles of the Tutte–Coxeter graph, exact 8-fold incidence of every `(v, off_port)` pair (`tc_incidence_eq_8`), the exact double-counting identity (`tc_double_counting_eq`), `8 a_15 - 4 b_8 - 8 c_7 ≥ 45` (`tc_double_counting_bound`), `a_15 ≥ 18` cubic / `a_15 ≥ 14` general / `c_7 ≤ 3` at `a_15 = 15`, exact closure reductions (`tc_delta3_a15_ge_16_order_ge_346`, `tc_delta3_lt_345_cases`), and formal soundness of the SAT/DRAT `--add-slack-bound` cardinality constraint (`tc_slack_card_sound`, `tc_slack_card_n354_cubic`, `tc_slack_card_n338_delta3`, `tc_slack_card_n362_cubic`, `tc_slack_card_mixed3_delta3`). |
| `Sglab/Stage1Extensions.lean` | General Source 8-Packing Lift Theorem (`f_cubic_6_source_8packing`) and numerical corollary (`f_cubic_6_source_8packing_N702_S4`, order `≤ 10,498`), plus kernel-checked certification of all three `(3,10)`-cages (`cage310_1_certified`, `cage310_2_certified`, `cage310_3_certified`: simple, 3-regular, bipartite, `C4`-free, with explicit simple `C16` witnesses). |
| `Sglab/UnconditionalF6Data.lean`, `Sglab/UnconditionalF6.lean` | **Unconditional** kernel-checked proof of **`f_cubic_6_le_10498`** (`∃ G : FinGraph 10498, G.IsCubic ∧ ¬HasCycle 4 ∧ ¬HasCycle 8 ∧ ¬HasCycle 16 ∧ ¬HasCycle 32 ∧ ¬HasCycle 64`), embedding `k3_g16_n702.g6` in depth-5 4-ary trees (`Q4`), proving bipartiteness (`k3_g16_n702_bipartite`), exact girth `≥ 16` (`k3_g16_n702_girth16` via 2 kernel-verified automorphism generators acting transitively on the 351-vertex class + 1 Tree-Ball BFS check at root `1`), directed-cycle-free orientation `chosen`, and 4 BFS potentials for `S = [10, 402, 469, 296]`. |
| `Sglab/Stage2CTheory.lean` | Theoretical reduction & zero-oracle verifier soundness for Stage 2C (`f_{cubic,bip}(4) ≥ 86`): `bipartite_cycle_even`, `bipartite_no_c4_c8_dichotomy` (`C6` vs girth `≥ 10`), `CubicBipConfig` incidence graph (`toGraph_no_C4`), zero-oracle witness soundness (`check_c6_witness_sound`, `check_c8_witness_sound`, `check_c16_witness_sound`), lossless 2-orbit `C6` root dichotomy (`c6_two_orbit_dichotomy`: Orbit 1 `{0,4,6}` vs Orbit 2 `{0,6,7}`), and lossless girth-`≥ 10` Moore-tree bound (`girth10_moore_tree_62`: `62 ≤ N`). |
| `Sglab/CubicF4AndConnectivity.lean` | Formal vertex-deletion 2-connectivity (`Is2Connected`), sound iterative BFS checker (`is2Connected_of_check`), Master 2-Connectivity Preservation Theorem (`liftGraph_is2Connected`), kernel-verified **`f_cubic_4_le_78`** (`Petersen + 1·H_15 + 9·H_7`, 2-connected & 3-regular), and 2-connectivity certificates for `pet73v1`, `pet73v2`, `tc345`, `tc370`. |

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
#print axioms Sglab.tc_delta3_a15_ge_16_order_ge_346
#print axioms Sglab.tc_delta3_lt_345_cases
#print axioms Sglab.tc_slack_card_sound
#print axioms Sglab.tc_slack_card_n354_cubic
#print axioms Sglab.tc_slack_card_n338_delta3
#print axioms Sglab.tc_slack_card_n362_cubic
#print axioms Sglab.tc_slack_card_mixed3_delta3
#print axioms Sglab.f_cubic_6_source_8packing
#print axioms Sglab.f_cubic_6_source_8packing_N702_S4
#print axioms Sglab.cage310_1_certified
#print axioms Sglab.cage310_2_certified
#print axioms Sglab.cage310_3_certified
#print axioms Sglab.k3_g16_n702_bipartite
#print axioms Sglab.k3_g16_n702_girth16
#print axioms Sglab.f_cubic_6_le_10498
#print axioms Sglab.bipartite_cycle_even
#print axioms Sglab.bipartite_no_c4_c8_dichotomy
#print axioms Sglab.CubicBipConfig.toGraph_no_C4
#print axioms Sglab.CubicBipConfig.check_c6_witness_sound
#print axioms Sglab.CubicBipConfig.check_c8_witness_sound
#print axioms Sglab.CubicBipConfig.check_c16_witness_sound
#print axioms Sglab.CubicBipConfig.c6_two_orbit_dichotomy
#print axioms Sglab.CubicBipConfig.girth10_moore_tree_62
#print axioms Sglab.liftGraph_is2Connected
#print axioms Sglab.f_cubic_4_le_78
#print axioms Sglab.pet73v1_is2Connected
#print axioms Sglab.pet73v2_is2Connected
#print axioms Sglab.tc345_is2Connected
#print axioms Sglab.tc370_is2Connected
EOF
```
