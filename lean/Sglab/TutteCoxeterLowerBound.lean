import Sglab.Graph
import Sglab.GadgetLift
import Sglab.Gadgets
import Sglab.Records

/-!
# Sglab.TutteCoxeterLowerBound — Kernel-Verified Double-Counting & DRAT Slack-Bound Soundness

Formalizes the exact double-counting lower bound on the Tutte–Coxeter graph (`n = 30`,
90 distinct 8-cycles) for the `{H_15, H_8*, H_7}` 3-port gadget family, proving with
zero `sorry`, zero custom axioms, and zero `native_decide`:
  1. All 90 listed 8-cycles (`tcC8Cycles`) are valid simple 8-cycles of `tutteCoxeterBase`,
     and every `(vertex, off-cycle port) : Fin 30 × Fin 3` lies on **exact 8** of them.
  2. **Exact Double-Counting Identity (`tc_double_counting_eq`)**:
     For ANY assignment `kind : Fin 30 → TCGadgetKind` (`H15`, `H8s`, `H7`) and ANY
     port orientation `choice : Fin 30 → Fin 3`:
       `∑_{C ∈ tcC8} weight(C) + 8 * b8 + 16 * c7 = 2160 + 16 * a15`,
     where `a15, b8, c7` are the counts of `H_15`, `H_8*`, `H_7`.
  3. **Exact Linear Inequality (`tc_double_counting_bound`)**:
     If every 8-cycle satisfies the lower-bound criterion `weight(C) ≥ 25` (so `8 + weight(C) ≥ 33`),
     then `45 + 4 * b8 + 8 * c7 ≤ 8 * a15` (i.e., `8 a_15 - 4 b_8 - 8 c_7 ≥ 45`), yielding:
       - `tc_cubic_a15_ge_18`: if `b8 = 0` (cubic), then `a15 ≥ 18` and order `≥ 354`,
       - `tc_delta3_a15_ge_14`: always `a15 ≥ 14` and order `≥ 338`,
       - `tc_delta3_a15_15_c7_le_3`: if `a15 = 15`, then `c7 ≤ 3` and order `≥ 342`.
  4. **Formal Soundness of the SAT/DRAT Slack Cardinality Bound (`tc_slack_card_sound`)**:
     If every 8-cycle has `weight(C) ≥ 25`, then the number of 8-cycles with `weight(C) ≥ 26`
     satisfies `#{C | weight(C) ≥ 26} + 90 + 8 * b8 + 16 * c7 ≤ 16 * a15`
     (in particular `≤ 6` for both `(a15=18, b8=0, c7=12)` at `n=354` and `(a15=14, b8=16, c7=0)` at `n=338`),
     formally closing the `--add-slack-bound` lemma used by our DRAT and CaDiCaL 1.5.3 UNSAT proofs!
-/

namespace Sglab
open FinGraph

/-! ### 1. The 90 Distinct 8-Cycles of Tutte–Coxeter (`n = 30`) -/

/-- All 90 canonical 8-cycles of the Tutte–Coxeter graph `tutteCoxeterBase`. -/
def tcC8Cycles : List (List Nat) := [
  [0, 1, 2, 3, 4, 5, 18, 17],
  [0, 1, 2, 3, 4, 13, 12, 29],
  [0, 1, 2, 3, 26, 25, 16, 17],
  [0, 1, 2, 3, 26, 27, 28, 29],
  [0, 1, 2, 9, 8, 7, 28, 29],
  [0, 1, 2, 9, 8, 15, 16, 17],
  [0, 1, 2, 9, 10, 11, 12, 29],
  [0, 1, 2, 9, 10, 19, 18, 17],
  [0, 1, 22, 21, 14, 13, 12, 29],
  [0, 1, 22, 21, 14, 15, 16, 17],
  [0, 1, 22, 21, 20, 19, 18, 17],
  [0, 1, 22, 21, 20, 27, 28, 29],
  [0, 1, 22, 23, 6, 5, 18, 17],
  [0, 1, 22, 23, 6, 7, 28, 29],
  [0, 1, 22, 23, 24, 11, 12, 29],
  [0, 1, 22, 23, 24, 25, 16, 17],
  [0, 17, 16, 15, 8, 7, 28, 29],
  [0, 17, 16, 15, 14, 13, 12, 29],
  [0, 17, 16, 25, 24, 11, 12, 29],
  [0, 17, 16, 25, 26, 27, 28, 29],
  [0, 17, 18, 5, 4, 13, 12, 29],
  [0, 17, 18, 5, 6, 7, 28, 29],
  [0, 17, 18, 19, 10, 11, 12, 29],
  [0, 17, 18, 19, 20, 27, 28, 29],
  [1, 2, 3, 4, 5, 6, 23, 22],
  [1, 2, 3, 4, 13, 14, 21, 22],
  [1, 2, 3, 26, 25, 24, 23, 22],
  [1, 2, 3, 26, 27, 20, 21, 22],
  [1, 2, 9, 8, 7, 6, 23, 22],
  [1, 2, 9, 8, 15, 14, 21, 22],
  [1, 2, 9, 10, 11, 24, 23, 22],
  [1, 2, 9, 10, 19, 20, 21, 22],
  [2, 3, 4, 5, 6, 7, 8, 9],
  [2, 3, 4, 5, 18, 19, 10, 9],
  [2, 3, 4, 13, 12, 11, 10, 9],
  [2, 3, 4, 13, 14, 15, 8, 9],
  [2, 3, 26, 25, 16, 15, 8, 9],
  [2, 3, 26, 25, 24, 11, 10, 9],
  [2, 3, 26, 27, 20, 19, 10, 9],
  [2, 3, 26, 27, 28, 7, 8, 9],
  [3, 4, 5, 6, 7, 28, 27, 26],
  [3, 4, 5, 6, 23, 24, 25, 26],
  [3, 4, 5, 18, 17, 16, 25, 26],
  [3, 4, 5, 18, 19, 20, 27, 26],
  [3, 4, 13, 12, 11, 24, 25, 26],
  [3, 4, 13, 12, 29, 28, 27, 26],
  [3, 4, 13, 14, 15, 16, 25, 26],
  [3, 4, 13, 14, 21, 20, 27, 26],
  [4, 5, 6, 7, 8, 15, 14, 13],
  [4, 5, 6, 7, 28, 29, 12, 13],
  [4, 5, 6, 23, 22, 21, 14, 13],
  [4, 5, 6, 23, 24, 11, 12, 13],
  [4, 5, 18, 17, 16, 15, 14, 13],
  [4, 5, 18, 19, 10, 11, 12, 13],
  [4, 5, 18, 19, 20, 21, 14, 13],
  [5, 6, 7, 8, 9, 10, 19, 18],
  [5, 6, 7, 8, 15, 16, 17, 18],
  [5, 6, 7, 28, 27, 20, 19, 18],
  [5, 6, 23, 22, 21, 20, 19, 18],
  [5, 6, 23, 24, 11, 10, 19, 18],
  [5, 6, 23, 24, 25, 16, 17, 18],
  [6, 7, 8, 9, 10, 11, 24, 23],
  [6, 7, 8, 15, 14, 21, 22, 23],
  [6, 7, 8, 15, 16, 25, 24, 23],
  [6, 7, 28, 27, 20, 21, 22, 23],
  [6, 7, 28, 27, 26, 25, 24, 23],
  [6, 7, 28, 29, 12, 11, 24, 23],
  [7, 8, 9, 10, 11, 12, 29, 28],
  [7, 8, 9, 10, 19, 20, 27, 28],
  [7, 8, 15, 14, 13, 12, 29, 28],
  [7, 8, 15, 14, 21, 20, 27, 28],
  [7, 8, 15, 16, 25, 26, 27, 28],
  [8, 9, 10, 11, 12, 13, 14, 15],
  [8, 9, 10, 11, 24, 25, 16, 15],
  [8, 9, 10, 19, 18, 17, 16, 15],
  [8, 9, 10, 19, 20, 21, 14, 15],
  [10, 11, 12, 13, 14, 21, 20, 19],
  [10, 11, 12, 29, 28, 27, 20, 19],
  [10, 11, 24, 23, 22, 21, 20, 19],
  [10, 11, 24, 25, 16, 17, 18, 19],
  [10, 11, 24, 25, 26, 27, 20, 19],
  [11, 12, 13, 14, 15, 16, 25, 24],
  [11, 12, 13, 14, 21, 22, 23, 24],
  [11, 12, 29, 28, 27, 26, 25, 24],
  [12, 13, 14, 21, 20, 27, 28, 29],
  [14, 15, 16, 17, 18, 19, 20, 21],
  [14, 15, 16, 25, 24, 23, 22, 21],
  [14, 15, 16, 25, 26, 27, 20, 21],
  [16, 17, 18, 19, 20, 27, 26, 25],
  [20, 21, 22, 23, 24, 25, 26, 27]
]

/-- Check that a `List Nat` is a valid simple 8-cycle of `tutteCoxeterBase`. -/
def isValidTC8Cycle (cyc : List Nat) : Bool :=
  cyc.length == 8 &&
  cyc.all (fun v => v < 30) &&
  (List.finRange 8).all (fun i =>
    (List.finRange 8).all (fun j =>
      if i == j then true else cyc.getD i.val 0 != cyc.getD j.val 0)) &&
  (List.finRange 8).all (fun i =>
    let u := cyc.getD i.val 0
    let v := cyc.getD ((i.val + 1) % 8) 0
    tripleHas (tripleAt tutteCoxeterTriples u) v)

/-- All 90 entries of `tcC8Cycles` are valid pairwise-distinct simple 8-cycles of `tutteCoxeterBase`. -/
theorem tcC8Cycles_length : tcC8Cycles.length = 90 := by decide
theorem tcC8Cycles_valid : tcC8Cycles.all isValidTC8Cycle = true := by decide
theorem tcC8Cycles_nodup : tcC8Cycles.Nodup := by decide

/-- Extract the 8 `(vertex, off-cycle neighbor port)` pairs along an 8-cycle `cyc`. -/
def cycleVertexOffPorts (cyc : List Nat) : List (Fin 30 × Fin 3) :=
  (List.finRange 8).map fun i =>
    let prev := cyc.getD ((i.val + 7) % 8) 0
    let cur  := cyc.getD i.val 0
    let nxt  := cyc.getD ((i.val + 1) % 8) 0
    let v : Fin 30 := ⟨cur % 30, Nat.mod_lt _ (by omega)⟩
    let t := tripleAt tutteCoxeterTriples cur
    let off : Fin 3 :=
      if t.1 != prev && t.1 != nxt then ⟨0, by omega⟩
      else if t.2.1 != prev && t.2.1 != nxt then ⟨1, by omega⟩
      else ⟨2, by omega⟩
    (v, off)

/-- Flatten all `90 × 8 = 720` incidences `(v, off)` across all 90 8-cycles of Tutte–Coxeter. -/
def tcC8Incidences : List (Fin 30 × Fin 3) :=
  tcC8Cycles.flatMap cycleVertexOffPorts

set_option maxRecDepth 4096 in
/-- **Exact Symmetry Lemma (`tc_incidence_eq_8`)**:
    Every `(v, off) : Fin 30 × Fin 3` appears **exact 8 times** across the 90 8-cycles of Tutte–Coxeter! -/
theorem tc_incidence_eq_8 :
    ∀ (v : Fin 30) (off : Fin 3),
      (tcC8Incidences.filter (fun p => p == (v, off))).length = 8 := by
  decide

/-! ### 2. Gadget Assignment Model `{H_15, H_8*, H_7}` and Double-Counting Identity -/

/-- Choice of 3-port gadget from `{H_15, H_8*, H_7}` at each base vertex of Tutte–Coxeter. -/
inductive TCGadgetKind where
  | H15
  | H8s
  | H7
  deriving DecidableEq

/-- Per-vertex gadget order (`15`, `8`, or `7`). -/
def TCGadgetKind.order : TCGadgetKind → Nat
  | .H15 => 15
  | .H8s => 8
  | .H7  => 7

/-- Convert a `TCGadgetKind` to its kernel-verified `Gadget3`. -/
def TCGadgetKind.toGadget : TCGadgetKind → Gadget3
  | .H15 => Sglab.H15
  | .H8s => Sglab.H8star
  | .H7  => Sglab.H7

/-- Internal path-length lower bound contributed by vertex `v` when its off-cycle base port is `off`
    and its distinguished port slot `0` is placed on base port `choice v`:
      - `H15`: `5` if `off = choice v`, else `3`
      - `H8s`: `2` if `off = choice v`, else `3`
      - `H7`:  `3` if `off = choice v`, else `2`. -/
def tcVertexWeight (kind : Fin 30 → TCGadgetKind) (choice : Fin 30 → Fin 3)
    (v : Fin 30) (off : Fin 3) : Nat :=
  match kind v with
  | .H15 => if off == choice v then 5 else 3
  | .H8s => if off == choice v then 2 else 3
  | .H7  => if off == choice v then 3 else 2

/-- Verify that `tcVertexWeight` matches `liftWeight` exactly for any adjacent triple `(prev, cur, nxt)`! -/
theorem tcVertexWeight_eq_liftWeight (kind : Fin 30 → TCGadgetKind) (choice : Fin 30 → Fin 3)
    (cur : Fin 30) (pa pb off : Fin 3)
    (hpa : pa ≠ off) (hpb : pb ≠ off) (hab : pa ≠ pb) :
    tcVertexWeight kind choice cur off =
      (kind cur).toGadget.distLower (rotPerm (choice cur) pa) (rotPerm (choice cur) pb) := by
  have hcases : ∀ (c a b o : Fin 3), a ≠ o → b ≠ o → a ≠ b →
      (if o == c then 5 else 3) = H15.distLower (rotPerm c a) (rotPerm c b) ∧
      (if o == c then 2 else 3) = H8star.distLower (rotPerm c a) (rotPerm c b) ∧
      (if o == c then 3 else 2) = H7.distLower (rotPerm c a) (rotPerm c b) := by
    decide
  obtain ⟨h15, h8, h7⟩ := hcases (choice cur) pa pb off hpa hpb hab
  cases hk : kind cur
  · simpa [tcVertexWeight, TCGadgetKind.toGadget, hk] using h15
  · simpa [tcVertexWeight, TCGadgetKind.toGadget, hk] using h8
  · simpa [tcVertexWeight, TCGadgetKind.toGadget, hk] using h7

/-- Total lower-bound internal weight `∑_{i=0}^7 w(v_i, off_i)` along an 8-cycle `cyc`. -/
def tcCycleWeight (kind : Fin 30 → TCGadgetKind) (choice : Fin 30 → Fin 3) (cyc : List Nat) : Nat :=
  (cycleVertexOffPorts cyc).foldl (fun acc p => acc + tcVertexWeight kind choice p.1 p.2) 0

/-- Counts `a15`, `b8`, `c7` of `H_15`, `H_8*`, `H_7` across `Fin 30`. -/
def countKind (kind : Fin 30 → TCGadgetKind) (k : TCGadgetKind) : Nat :=
  ((List.finRange 30).filter (fun v => decide (kind v = k))).length

/-- Total lifted vertex order `15*a15 + 8*b8 + 7*c7`. -/
def tcTotalOrder (kind : Fin 30 → TCGadgetKind) : Nat :=
  (List.finRange 30).foldl (fun acc v => acc + (kind v).order) 0

theorem tc_counts_sum (kind : Fin 30 → TCGadgetKind) :
    countKind kind .H15 + countKind kind .H8s + countKind kind .H7 = 30 := by
  have hgen : ∀ (xs : List (Fin 30)),
      (xs.filter (fun v => decide (kind v = .H15))).length +
      (xs.filter (fun v => decide (kind v = .H8s))).length +
      (xs.filter (fun v => decide (kind v = .H7))).length = xs.length := by
    intro xs
    induction xs with
    | nil => simp
    | cons x xs ih =>
      simp only [List.filter_cons, List.length_cons]
      cases kind x <;> simp <;> omega
  simpa [countKind] using hgen (List.finRange 30)

theorem tcTotalOrder_eq (kind : Fin 30 → TCGadgetKind) :
    tcTotalOrder kind =
      15 * countKind kind .H15 + 8 * countKind kind .H8s + 7 * countKind kind .H7 := by
  have hgen : ∀ (xs : List (Fin 30)),
      xs.foldl (fun acc v => acc + (kind v).order) 0 =
        15 * (xs.filter (fun v => decide (kind v = .H15))).length +
         8 * (xs.filter (fun v => decide (kind v = .H8s))).length +
         7 * (xs.filter (fun v => decide (kind v = .H7))).length := by
    intro xs
    induction xs with
    | nil => simp
    | cons x xs ih =>
      simp only [List.foldl_cons, Nat.zero_add, List.filter_cons]
      rw [foldl_add_shift, ih]
      cases kind x <;> simp [TCGadgetKind.order] <;> omega
  exact hgen (List.finRange 30)

/-! ### 3. Generic Sum Reordering Lemma (`foldl_eq_sum_count`) -/

private theorem foldl_add_flatMap {α β : Type} (xs : List α) (g : α → List β) (f : β → Nat) :
    (xs.flatMap g).foldl (fun acc b => acc + f b) 0 =
      xs.foldl (fun acc a => acc + (g a).foldl (fun a2 b => a2 + f b) 0) 0 := by
  induction xs with
  | nil => simp
  | cons x xs ih =>
    simp only [List.flatMap_cons, List.foldl_append, List.foldl_cons, Nat.zero_add]
    rw [foldl_add_shift f (xs.flatMap g),
        foldl_add_shift (fun a => (g a).foldl (fun a2 b => a2 + f b) 0) xs, ih]

/-- Decompose a sum over `xs : List α` by multiplicity of each element in a `Nodup` universe `U`. -/
private theorem foldl_eq_sum_mult {α : Type} [DecidableEq α]
    (U : List α) (hnd : U.Nodup) (f : α → Nat) :
    ∀ (xs : List α), (∀ x, x ∈ xs → x ∈ U) →
      xs.foldl (fun acc x => acc + f x) 0 =
        U.foldl (fun acc u => acc + (xs.filter (fun x => x == u)).length * f u) 0
  | [], _ => by
    have hzero : ∀ (ys : List α), ys.foldl (fun acc u => acc + 0 * f u) 0 = 0 := by
      intro ys; induction ys with
      | nil => rfl
      | cons y ys ih =>
        simp only [List.foldl_cons]
        rw [Nat.zero_mul, Nat.add_zero]
        exact ih
    simpa using (hzero U).symm
  | x :: xs, hsub => by
    have ih := foldl_eq_sum_mult U hnd f xs (fun y hy => hsub y (List.mem_cons_of_mem x hy))
    simp only [List.foldl_cons, Nat.zero_add]
    rw [foldl_add_shift, ih]
    -- Show adding `x` increments the `u = x` term by `f x` and leaves all `u ≠ x` unchanged!
    have hstep : ∀ (ys : List α), ys.Nodup →
        ys.foldl (fun acc u => acc + ((x :: xs).filter (fun z => z == u)).length * f u) 0 =
          (if x ∈ ys then f x else 0) +
          ys.foldl (fun acc u => acc + (xs.filter (fun z => z == u)).length * f u) 0 := by
      intro ys
      induction ys with
      | nil => intro _; simp
      | cons y ys ihy =>
        intro hynd
        rw [List.nodup_cons] at hynd
        simp only [List.foldl_cons, Nat.zero_add, List.filter_cons]
        rw [foldl_add_shift (fun u => ((if x == u then x :: xs.filter (fun z => z == u) else xs.filter (fun z => z == u))).length * f u) ys,
            foldl_add_shift (fun u => (xs.filter (fun z => z == u)).length * f u) ys]
        have hih' := ihy hynd.2
        have heq_tl : ys.foldl (fun acc u => acc + ((if x == u then x :: xs.filter (fun z => z == u) else xs.filter (fun z => z == u))).length * f u) 0 =
            ys.foldl (fun acc u => acc + ((x :: xs).filter (fun z => z == u)).length * f u) 0 := by
          congr 1; funext acc u; simp [List.filter_cons]
        rw [heq_tl, hih']
        by_cases hxy : x = y
        · subst hxy
          have hnot : x ∉ ys := hynd.1
          simp only [beq_self_eq_true, ↓reduceIte, List.length_cons, List.mem_cons, true_or, hnot]
          rw [Nat.add_mul, Nat.one_mul]; omega
        · have hbeq : (x == y) = false := beq_false_of_ne hxy
          simp only [hbeq, Bool.false_eq_true, ↓reduceIte, List.mem_cons, hxy, false_or]
          omega
    have hxU : x ∈ U := hsub x (List.mem_cons_self ..)
    have hs := hstep U hnd
    simp only [hxU, ↓reduceIte] at hs
    exact hs.symm

/-- Universe of all 90 `(v, off) : Fin 30 × Fin 3` pairs. -/
def allVertexPorts : List (Fin 30 × Fin 3) :=
  (List.finRange 30).flatMap (fun v => (List.finRange 3).map (fun o => (v, o)))

theorem allVertexPorts_nodup : allVertexPorts.Nodup := by decide

theorem allVertexPorts_mem (p : Fin 30 × Fin 3) : p ∈ allVertexPorts := by
  simp only [allVertexPorts, List.mem_flatMap, List.mem_map, List.mem_finRange, true_and]
  exact ⟨p.1, p.2, rfl⟩

/-- **Theorem 1 (`tc_double_counting_eq`) — Exact Double-Counting Identity on Tutte–Coxeter**:
    For ANY gadget assignment `kind : Fin 30 → TCGadgetKind` and ANY port choices `choice : Fin 30 → Fin 3`:
      `∑_{C ∈ tcC8} tcCycleWeight(C) + 8 * b8 + 16 * c7 = 2160 + 16 * a15`. -/
theorem tc_double_counting_eq (kind : Fin 30 → TCGadgetKind) (choice : Fin 30 → Fin 3) :
    tcC8Cycles.foldl (fun acc C => acc + tcCycleWeight kind choice C) 0 +
      8 * countKind kind .H8s + 16 * countKind kind .H7 =
    2160 + 16 * countKind kind .H15 := by
  let w (p : Fin 30 × Fin 3) : Nat := tcVertexWeight kind choice p.1 p.2
  have hflat : tcC8Cycles.foldl (fun acc C => acc + tcCycleWeight kind choice C) 0 =
      tcC8Incidences.foldl (fun acc p => acc + w p) 0 := by
    symm; exact foldl_add_flatMap tcC8Cycles cycleVertexOffPorts w
  rw [hflat, foldl_eq_sum_mult allVertexPorts allVertexPorts_nodup w tcC8Incidences (fun p _ => allVertexPorts_mem p)]
  -- Replace each `(tcC8Incidences.filter (· == p)).length` by `8` using `tc_incidence_eq_8`!
  have h8 : allVertexPorts.foldl (fun acc p => acc + (tcC8Incidences.filter (fun x => x == p)).length * w p) 0 =
      allVertexPorts.foldl (fun acc p => acc + 8 * w p) 0 := by
    congr 1; funext acc p
    rw [tc_incidence_eq_8 p.1 p.2]
  rw [h8]
  -- Collapse `allVertexPorts = finRange 30 × finRange 3` into a sum over `v : Fin 30`!
  simp only [allVertexPorts]
  rw [foldl_add_flatMap (List.finRange 30) (fun v => (List.finRange 3).map (fun o => (v, o))) (fun p => 8 * w p)]
  -- For each `v : Fin 30`, compute `∑_{o : Fin 3} 8 * w (v, o)`!
  have hperV : ∀ v : Fin 30,
      ((List.finRange 3).map (fun o => (v, o))).foldl (fun acc p => acc + 8 * w p) 0 =
        match kind v with
        | .H15 => 88
        | .H8s => 64
        | .H7  => 56 := by
    intro v
    have hfin3 : List.finRange 3 = [⟨0, by omega⟩, ⟨1, by omega⟩, ⟨2, by omega⟩] := rfl
    rw [hfin3]
    simp only [List.map_cons, List.map_nil, List.foldl_cons, List.foldl_nil, Nat.zero_add, w, tcVertexWeight]
    have hc3 : choice v = ⟨0, by omega⟩ ∨ choice v = ⟨1, by omega⟩ ∨ choice v = ⟨2, by omega⟩ := by
      have hlt := (choice v).isLt
      have : (choice v).val = 0 ∨ (choice v).val = 1 ∨ (choice v).val = 2 := by omega
      rcases this with h | h | h
      · left; exact Fin.ext h
      · right; left; exact Fin.ext h
      · right; right; exact Fin.ext h
    cases kind v <;> rcases hc3 with h | h | h <;> rw [h] <;> rfl
  have hsumV : ∀ (xs : List (Fin 30)),
      xs.foldl (fun acc v => acc + ((List.finRange 3).map (fun o => (v, o))).foldl (fun a2 p => a2 + 8 * w p) 0) 0 +
      8 * (xs.filter (fun v => decide (kind v = .H8s))).length +
      16 * (xs.filter (fun v => decide (kind v = .H7))).length =
      72 * xs.length + 16 * (xs.filter (fun v => decide (kind v = .H15))).length := by
    intro xs
    induction xs with
    | nil => simp
    | cons x xs ih =>
      simp only [List.foldl_cons, Nat.zero_add, List.filter_cons, List.length_cons]
      rw [foldl_add_shift, hperV x]
      cases kind x <;> simp <;> omega
  have hfinal := hsumV (List.finRange 30)
  simp only [List.length_finRange] at hfinal
  simpa [countKind] using hfinal

/-! ### 4. Consequences: Exact Lower Bounds & DRAT Slack-Bound Soundness -/

/-- **Theorem 2 (`tc_double_counting_bound`)**:
    If every one of the 90 8-cycles of Tutte–Coxeter has `tcCycleWeight C ≥ 25`
    (so every lifted 8-cycle has lower bound `8 + 25 = 33 > 32`), then:
      `45 + 4 * b8 + 8 * c7 ≤ 8 * a15`  (equivalently `8 a_15 - 4 b_8 - 8 c_7 ≥ 45`). -/
theorem tc_double_counting_bound (kind : Fin 30 → TCGadgetKind) (choice : Fin 30 → Fin 3)
    (h25 : ∀ C ∈ tcC8Cycles, 25 ≤ tcCycleWeight kind choice C) :
    45 + 4 * countKind kind .H8s + 8 * countKind kind .H7 ≤ 8 * countKind kind .H15 := by
  have hlb : ∀ (xs : List (List Nat)), (∀ C ∈ xs, 25 ≤ tcCycleWeight kind choice C) →
      25 * xs.length ≤ xs.foldl (fun acc C => acc + tcCycleWeight kind choice C) 0 := by
    intro xs
    induction xs with
    | nil => intro _; simp
    | cons C xs ih =>
      intro h
      simp only [List.foldl_cons, Nat.zero_add, List.length_cons]
      rw [foldl_add_shift]
      have h1 := h C (List.mem_cons_self ..)
      have h2 := ih (fun C' hC' => h C' (List.mem_cons_of_mem C hC'))
      omega
  have hsum_lb := hlb tcC8Cycles h25
  rw [tcC8Cycles_length] at hsum_lb
  have heq := tc_double_counting_eq kind choice
  omega

/-- **Corollary 2a (`tc_cubic_a15_ge_18`)**:
    For cubic assignments (`b8 = 0`, using only `{H_15, H_7}`), `a15 ≥ 18` and total order `≥ 354`. -/
theorem tc_cubic_a15_ge_18 (kind : Fin 30 → TCGadgetKind) (choice : Fin 30 → Fin 3)
    (h25 : ∀ C ∈ tcC8Cycles, 25 ≤ tcCycleWeight kind choice C)
    (hcubic : countKind kind .H8s = 0) :
    18 ≤ countKind kind .H15 ∧ 354 ≤ tcTotalOrder kind := by
  have hb := tc_double_counting_bound kind choice h25
  have hs := tc_counts_sum kind
  have ho := tcTotalOrder_eq kind
  omega

/-- **Corollary 2b (`tc_delta3_a15_ge_14`)**:
    For ANY `{H_15, H_8*, H_7}` assignment (`δ ≥ 3`), `a15 ≥ 14` and total order `≥ 338`. -/
theorem tc_delta3_a15_ge_14 (kind : Fin 30 → TCGadgetKind) (choice : Fin 30 → Fin 3)
    (h25 : ∀ C ∈ tcC8Cycles, 25 ≤ tcCycleWeight kind choice C) :
    14 ≤ countKind kind .H15 ∧ 338 ≤ tcTotalOrder kind := by
  have hb := tc_double_counting_bound kind choice h25
  have hs := tc_counts_sum kind
  have ho := tcTotalOrder_eq kind
  omega

/-- **Corollary 2c (`tc_delta3_a15_15_c7_le_3`)**:
    Whenever `a15 = 15`, at most `3` copies of `H_7` can be used (`c7 ≤ 3`), hence total order `≥ 342`. -/
theorem tc_delta3_a15_15_c7_le_3 (kind : Fin 30 → TCGadgetKind) (choice : Fin 30 → Fin 3)
    (h25 : ∀ C ∈ tcC8Cycles, 25 ≤ tcCycleWeight kind choice C)
    (ha15 : countKind kind .H15 = 15) :
    countKind kind .H7 ≤ 3 ∧ 342 ≤ tcTotalOrder kind := by
  have hb := tc_double_counting_bound kind choice h25
  have hs := tc_counts_sum kind
  have ho := tcTotalOrder_eq kind
  omega

/-- **Theorem 3 (`tc_slack_card_sound`) — Formal Soundness of the SAT/DRAT `--add-slack-bound` Lemma**:
    If every one of the 90 8-cycles satisfies `tcCycleWeight C ≥ 25`, then the number of 8-cycles
    with strict surplus (`tcCycleWeight C ≥ 26`, i.e., `sum_C ≥ 10` in shifted `w ∈ {0, 1, 3}` coordinates)
    is bounded above by the exact global slack budget:
      `#{C ∈ tcC8 | tcCycleWeight C ≥ 26} + 90 + 8 * b8 + 16 * c7 ≤ 16 * a15`!
    In particular:
      - Cubic `n = 354` (`a15 = 18, b8 = 0, c7 = 12`): at most `6` slack cycles!
      - `δ ≥ 3` `n = 338` (`a15 = 14, b8 = 16, c7 = 0`): at most `6` slack cycles! -/
theorem tc_slack_card_sound (kind : Fin 30 → TCGadgetKind) (choice : Fin 30 → Fin 3)
    (h25 : ∀ C ∈ tcC8Cycles, 25 ≤ tcCycleWeight kind choice C) :
    (tcC8Cycles.filter (fun C => decide (26 ≤ tcCycleWeight kind choice C))).length +
      90 + 8 * countKind kind .H8s + 16 * countKind kind .H7 ≤
    16 * countKind kind .H15 := by
  have hlb : ∀ (xs : List (List Nat)), (∀ C ∈ xs, 25 ≤ tcCycleWeight kind choice C) →
      25 * xs.length + (xs.filter (fun C => decide (26 ≤ tcCycleWeight kind choice C))).length ≤
        xs.foldl (fun acc C => acc + tcCycleWeight kind choice C) 0 := by
    intro xs
    induction xs with
    | nil => intro _; simp
    | cons C xs ih =>
      intro h
      simp only [List.foldl_cons, Nat.zero_add, List.filter_cons, List.length_cons]
      rw [foldl_add_shift]
      have h1 := h C (List.mem_cons_self ..)
      have h2 := ih (fun C' hC' => h C' (List.mem_cons_of_mem C hC'))
      by_cases h26 : 26 ≤ tcCycleWeight kind choice C
      · simp only [decide_eq_true h26, ↓reduceIte, List.length_cons]; omega
      · simp only [decide_eq_false h26, Bool.false_eq_true, ↓reduceIte]; omega
  have hsum := hlb tcC8Cycles h25
  rw [tcC8Cycles_length] at hsum
  have heq := tc_double_counting_eq kind choice
  omega

/-- Concrete DRAT instantiation 1: at `n = 354` (`a15 = 18, b8 = 0`), at most `6` 8-cycles can have weight `≥ 26`. -/
theorem tc_slack_card_n354_cubic (kind : Fin 30 → TCGadgetKind) (choice : Fin 30 → Fin 3)
    (h25 : ∀ C ∈ tcC8Cycles, 25 ≤ tcCycleWeight kind choice C)
    (ha15 : countKind kind .H15 = 18) (hb8 : countKind kind .H8s = 0) :
    (tcC8Cycles.filter (fun C => decide (26 ≤ tcCycleWeight kind choice C))).length ≤ 6 := by
  have hcard := tc_slack_card_sound kind choice h25
  have hs := tc_counts_sum kind
  omega

/-- Concrete DRAT instantiation 2: at `n = 338` (`a15 = 14, c7 = 0`), at most `6` 8-cycles can have weight `≥ 26`. -/
theorem tc_slack_card_n338_delta3 (kind : Fin 30 → TCGadgetKind) (choice : Fin 30 → Fin 3)
    (h25 : ∀ C ∈ tcC8Cycles, 25 ≤ tcCycleWeight kind choice C)
    (ha15 : countKind kind .H15 = 14) (hc7 : countKind kind .H7 = 0) :
    (tcC8Cycles.filter (fun C => decide (26 ≤ tcCycleWeight kind choice C))).length ≤ 6 := by
  have hcard := tc_slack_card_sound kind choice h25
  have hs := tc_counts_sum kind
  omega

/-- **Corollary 2d (`tc_delta3_a15_ge_16_order_ge_346`)**:
    For ANY valid `{H_15, H_8*, H_7}` assignment with `a15 ≥ 16`, the double-counting bound
    forces `c7 ≤ 3 * a15 - 42`, hence total order `tcTotalOrder kind ≥ 282 + 4 * a15 ≥ 346 > 345`. -/
theorem tc_delta3_a15_ge_16_order_ge_346 (kind : Fin 30 → TCGadgetKind) (choice : Fin 30 → Fin 3)
    (h25 : ∀ C ∈ tcC8Cycles, 25 ≤ tcCycleWeight kind choice C)
    (ha16 : 16 ≤ countKind kind .H15) :
    346 ≤ tcTotalOrder kind := by
  have hb := tc_double_counting_bound kind choice h25
  have hs := tc_counts_sum kind
  have ho := tcTotalOrder_eq kind
  omega

/-- **Corollary 2e (`tc_delta3_lt_345_cases`) — Exhaustive Reduction for Exact Minimum `345`**:
    Any valid `{H_15, H_8*, H_7}` assignment on Tutte–Coxeter with total order `< 345` MUST satisfy
    either `a15 ≤ 14` (ruled out by `n ≤ 338` DRAT proof) or `a15 = 15 ∧ c7 ∈ {1, 2, 3}`
    (ruled out by `n ∈ {342, 343, 344}` `drat-trim` proofs). -/
theorem tc_delta3_lt_345_cases (kind : Fin 30 → TCGadgetKind) (choice : Fin 30 → Fin 3)
    (h25 : ∀ C ∈ tcC8Cycles, 25 ≤ tcCycleWeight kind choice C)
    (hlt : tcTotalOrder kind < 345) :
    countKind kind .H15 ≤ 14 ∨
      (countKind kind .H15 = 15 ∧
        (countKind kind .H7 = 1 ∨ countKind kind .H7 = 2 ∨ countKind kind .H7 = 3)) := by
  by_cases ha14 : countKind kind .H15 ≤ 14
  · exact Or.inl ha14
  · by_cases ha15 : countKind kind .H15 = 15
    · right
      refine ⟨ha15, ?_⟩
      have hle3 := (tc_delta3_a15_15_c7_le_3 kind choice h25 ha15).1
      have hs := tc_counts_sum kind
      have ho := tcTotalOrder_eq kind
      omega
    · exfalso
      have hge16 : 16 ≤ countKind kind .H15 := by omega
      have hge346 := tc_delta3_a15_ge_16_order_ge_346 kind choice h25 hge16
      omega

/-- Concrete DRAT instantiation 3: for cubic `n ≤ 362` (`a15 ≤ 19, b8 = 0`), at most `38` 8-cycles
    can have weight `≥ 26` (certifying soundness of `--add-slack-bound` in our 56-leaf `drat-trim` closure). -/
theorem tc_slack_card_n362_cubic (kind : Fin 30 → TCGadgetKind) (choice : Fin 30 → Fin 3)
    (h25 : ∀ C ∈ tcC8Cycles, 25 ≤ tcCycleWeight kind choice C)
    (ha15 : countKind kind .H15 ≤ 19) (hb8 : countKind kind .H8s = 0) :
    (tcC8Cycles.filter (fun C => decide (26 ≤ tcCycleWeight kind choice C))).length ≤ 38 := by
  have hcard := tc_slack_card_sound kind choice h25
  have hs := tc_counts_sum kind
  omega

/-- Concrete DRAT instantiation 4: for mixed `δ ≥ 3` (`a15 ≤ 15, c7 ≥ k`), at most `30 - 8 * k`
    8-cycles can have weight `≥ 26` (`≤ 22` at `n = 344`, `≤ 14` at `n = 343`, `≤ 6` at `n = 342`),
    certifying soundness of `--mode mixed3 --add-slack-bound` in our `drat-trim` closure of `= 345`. -/
theorem tc_slack_card_mixed3_delta3 (kind : Fin 30 → TCGadgetKind) (choice : Fin 30 → Fin 3)
    (h25 : ∀ C ∈ tcC8Cycles, 25 ≤ tcCycleWeight kind choice C)
    (ha15 : countKind kind .H15 ≤ 15) (k : Nat) (hc7 : k ≤ countKind kind .H7) :
    (tcC8Cycles.filter (fun C => decide (26 ≤ tcCycleWeight kind choice C))).length + 8 * k ≤ 30 := by
  have hcard := tc_slack_card_sound kind choice h25
  have hs := tc_counts_sum kind
  omega

end Sglab
