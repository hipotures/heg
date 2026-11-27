import Sglab.Graph
import Sglab.Stage1Extensions

/-!
# Sglab.Stage2CTheory — Formal Theoretical Reduction & Zero-Oracle Verifier Soundness for Stage 2C

Proves with zero Mathlib, zero `sorry`, zero custom axioms, and zero `native_decide`:
  1. `bipartite_cycle_even`: every simple cycle in a bipartite graph has even length.
  2. `bipartite_no_c4_c8_dichotomy`: every simple bipartite graph avoiding `C4` and `C8`
     either contains a `6`-cycle (`HasCycle 6`) or has girth `≥ 10` (`∀ L < 10, ¬ HasCycle L`).
  3. `CubicBipConfig V` (3-uniform, 3-regular linear hypergraph representation of cubic
     bipartite `C4`-free graphs of order `2 * V`) and its incidence graph `toGraph : FinGraph (2 * V)`
     with kernel proofs of `IsBipartite` and `¬ HasCycle 4`.
  4. **Zero-Oracle Certificate Witness Soundness**:
     - `alternating_cycle_sound`: any alternating sequence of `m ≥ 2` distinct points and
       `m` distinct blocks yields `HasCycle (2 * m)` in `toGraph`.
     - `check_c6_witness_sound` (`m = 3`, matching `cubic_bipartite_girth10_cert_verify.cpp::check_c6`).
     - `check_c8_witness_sound` (`m = 4`, matching `cubic_bipartite_cert_verify.cpp::check_c8`
       and `cubic_bipartite_parallel.cpp::check_c8`).
     - `check_c16_witness_sound` (`m = 8`, matching `check_c16` in both verifiers).
  5. **Lossless Branch A Root Dichotomy (`c6_two_orbit_dichotomy`)**:
     Every `C6`-containing `CubicBipConfig V` has its 4th block on point `a0` falling into
     EXACTLY two exhaustive orbits: Orbit 1 (hitting the opposite spoke `x1`, i.e., `{0,4,6}`)
     or Orbit 2 (two fresh points disjoint from the 6-point triangle, i.e., `{0,6,7}`).
  6. **Lossless Branch B Moore-Tree Lower Bound (`girth10_moore_tree_62`)**:
     Every simple cubic graph of girth `≥ 10` contains an edge-rooted Moore tree of depth `4`
     having `62` pairwise distinct vertices (`31` on each side of the root edge), proving
     `62 ≤ n` (and justifying our lossless 15-block / 31-point Moore root!).
-/

namespace Sglab
open FinGraph

/-! ### 1. Bipartite Even-Cycle Theorem & `C6` vs. Girth-`≥ 10` Dichotomy -/

/-- Every simple cycle in a bipartite graph has even length. -/
theorem bipartite_cycle_even {n L : Nat} {G : FinGraph n}
    (hbip : IsBipartite G) (c : G.SimpleCycle L) : L % 2 = 0 := by
  obtain ⟨col, hcol⟩ := hbip
  have hL3 := c.hlen
  have hpar : ∀ k : Nat, k ≤ L →
      col (c.vert ⟨k % L, Nat.mod_lt _ (by omega)⟩) =
        if k % 2 == 0 then col (c.vert ⟨0, by omega⟩) else !col (c.vert ⟨0, by omega⟩) := by
    intro k
    induction k with
    | zero => intro _; simp
    | succ k ih =>
      intro hk
      have hprev := ih (by omega)
      have he := c.edge ⟨k % L, Nat.mod_lt _ (by omega)⟩
      have hm : (k % L + 1) % L = (k + 1) % L := by rw [Nat.mod_add_mod]
      have he' : G.adj (c.vert ⟨k % L, Nat.mod_lt _ (by omega)⟩)
          (c.vert ⟨(k + 1) % L, Nat.mod_lt _ (by omega)⟩) = true := by
        simpa [hm] using he
      have hne := hcol _ _ he'
      have hflip : col (c.vert ⟨(k + 1) % L, Nat.mod_lt _ (by omega)⟩) =
          !col (c.vert ⟨k % L, Nat.mod_lt _ (by omega)⟩) := by
        cases ha : col (c.vert ⟨k % L, Nat.mod_lt _ (by omega)⟩) <;>
        cases hb : col (c.vert ⟨(k + 1) % L, Nat.mod_lt _ (by omega)⟩)
        · exact absurd (ha.trans hb.symm) hne
        · rfl
        · rfl
        · exact absurd (ha.trans hb.symm) hne
      rw [hflip, hprev]
      by_cases hke : k % 2 = 0
      · have hk1 : (k + 1) % 2 = 1 := by omega
        simp [hke, hk1]
      · have hk1 : (k + 1) % 2 = 0 := by omega
        have hke_f : (k % 2 == 0) = false := beq_false_of_ne hke
        simp [hke_f, hk1]
  have hL := hpar L (Nat.le_refl L)
  simp only [Nat.mod_self] at hL
  by_cases heven : L % 2 = 0
  · exact heven
  · exfalso
    have hf : (L % 2 == 0) = false := beq_false_of_ne heven
    simp only [hf, Bool.false_eq_true, ↓reduceIte] at hL
    cases hc : col (c.vert ⟨0, by omega⟩) <;> rw [hc] at hL <;> cases hL

/-- **Stage 2C Branch Dichotomy**:
    Any bipartite graph avoiding `C4` and `C8` either contains a `6`-cycle (Branch A:
    Berge-triangle search) or has girth `≥ 10` (Branch B: Moore-tree search). -/
theorem bipartite_no_c4_c8_dichotomy {n : Nat} {G : FinGraph n}
    (hbip : IsBipartite G) (h4 : ¬ G.HasCycle 4) (h8 : ¬ G.HasCycle 8) :
    G.HasCycle 6 ∨ (∀ L : Nat, L < 10 → ¬ G.HasCycle L) := by
  by_cases h6 : G.HasCycle 6
  · exact Or.inl h6
  · right
    intro L hL ⟨c⟩
    have hL3 := c.hlen
    have heven := bipartite_cycle_even hbip c
    have hcases : L = 4 ∨ L = 6 ∨ L = 8 := by omega
    rcases hcases with rfl | rfl | rfl
    · exact h4 ⟨c⟩
    · exact h6 ⟨c⟩
    · exact h8 ⟨c⟩

/-! ### 2. 3-Uniform 3-Regular Linear Hypergraph (`CubicBipConfig V`) & Incidence Graph -/

/-- A 3-uniform, 3-regular linear hypergraph on `V` points and `V` blocks — the exact
    combinatorial object explored by Stage 2C (`C4`-free cubic bipartite graphs of order `2*V`). -/
structure CubicBipConfig (V : Nat) where
  inc : Fin V → Fin V → Bool
  linear : ∀ (b1 b2 p1 p2 : Fin V),
    b1 ≠ b2 → p1 ≠ p2 →
    inc p1 b1 = true → inc p2 b1 = true →
    inc p1 b2 = true → inc p2 b2 = true → False
  blockPts : Fin V → Fin 3 → Fin V
  blockPts_inj : ∀ b : Fin V, ∀ i j : Fin 3, blockPts b i = blockPts b j → i = j
  blockPts_iff : ∀ (b p : Fin V), inc p b = true ↔ ∃ i : Fin 3, blockPts b i = p
  pointBlks : Fin V → Fin 3 → Fin V
  pointBlks_inj : ∀ p : Fin V, ∀ i j : Fin 3, pointBlks p i = pointBlks p j → i = j
  pointBlks_iff : ∀ (p b : Fin V), inc p b = true ↔ ∃ i : Fin 3, pointBlks p i = b

namespace CubicBipConfig

variable {V : Nat}

/-- Embed point `p : Fin V` into the incidence graph `Fin (2 * V)` as `p`. -/
def ptVert (p : Fin V) : Fin (2 * V) := ⟨p.val, by omega⟩

/-- Embed block `b : Fin V` into the incidence graph `Fin (2 * V)` as `V + b`. -/
def blkVert (b : Fin V) : Fin (2 * V) := ⟨V + b.val, by omega⟩

/-- The bipartite Levi / incidence graph of `H : CubicBipConfig V` on `2 * V` vertices:
    vertices `0..V-1` are points, vertices `V..2*V-1` are blocks. -/
def toGraph (H : CubicBipConfig V) : FinGraph (2 * V) where
  adj u v :=
    if hu : u.val < V then
      if hv : V ≤ v.val then H.inc ⟨u.val, hu⟩ ⟨v.val - V, by omega⟩ else false
    else
      if hv : v.val < V then H.inc ⟨v.val, hv⟩ ⟨u.val - V, by omega⟩ else false
  symm u v := by
    by_cases hu : u.val < V <;> by_cases hv : v.val < V
    · have hv' : ¬ (V ≤ v.val) := by omega
      have hu' : ¬ (V ≤ u.val) := by omega
      simp [hu, hv, hv', hu']
    · have hv' : V ≤ v.val := by omega
      simp [hu, hv, hv']
    · have hu' : V ≤ u.val := by omega
      simp [hu, hv, hu']
    · simp [hu, hv]
  loopless u := by
    by_cases hu : u.val < V
    · have hu' : ¬ (V ≤ u.val) := by omega
      simp [hu, hu']
    · simp [hu]

theorem toGraph_adj_pt_blk (H : CubicBipConfig V) (p b : Fin V) :
    H.toGraph.adj (ptVert p) (blkVert b) = H.inc p b := by
  have hp : p.val < V := p.isLt
  have hb : V ≤ V + b.val := by omega
  have hsub : (V + b.val) - V = b.val := by omega
  simp only [toGraph, ptVert, blkVert, hp, hb, ↓reduceDIte]
  congr 1; exact Fin.ext hsub

theorem toGraph_adj_blk_pt (H : CubicBipConfig V) (b p : Fin V) :
    H.toGraph.adj (blkVert b) (ptVert p) = H.inc p b := by
  rw [H.toGraph.symm, toGraph_adj_pt_blk]

theorem toGraph_isBipartite (H : CubicBipConfig V) : IsBipartite H.toGraph := by
  refine ⟨fun u => decide (V ≤ u.val), fun u v huv => ?_⟩
  by_cases hu : u.val < V <;> by_cases hv : v.val < V
  · have hv' : ¬ (V ≤ v.val) := by omega
    simp [toGraph, hu, hv'] at huv
  · have hu' : ¬ (V ≤ u.val) := by omega
    have hv' : V ≤ v.val := by omega
    simp [hu', hv']
  · have hu' : V ≤ u.val := by omega
    have hv' : ¬ (V ≤ v.val) := by omega
    simp [hu', hv']
  · simp [toGraph, hu, hv] at huv

private theorem toGraph_adj_inc_pt_blk (H : CubicBipConfig V) (u v : Fin (2 * V))
    (hu : u.val < V) (hv : V ≤ v.val) (h : H.toGraph.adj u v = true) :
    H.inc ⟨u.val, hu⟩ ⟨v.val - V, by omega⟩ = true := by
  simp only [toGraph, hu, hv, ↓reduceDIte] at h
  exact h

private theorem toGraph_adj_inc_blk_pt (H : CubicBipConfig V) (u v : Fin (2 * V))
    (hu : V ≤ u.val) (hv : v.val < V) (h : H.toGraph.adj u v = true) :
    H.inc ⟨v.val, hv⟩ ⟨u.val - V, by omega⟩ = true := by
  have hu' : ¬ (u.val < V) := by omega
  simp only [toGraph, hu', hv, ↓reduceDIte] at h
  exact h

/-- Every linear 3-uniform hypergraph has a `C4`-free incidence graph. -/
theorem toGraph_no_C4 (H : CubicBipConfig V) : ¬ H.toGraph.HasCycle 4 := by
  rintro ⟨c⟩
  have he0 : H.toGraph.adj (c.vert ⟨0, by decide⟩) (c.vert ⟨1, by decide⟩) = true := c.edge ⟨0, by decide⟩
  have he1 : H.toGraph.adj (c.vert ⟨1, by decide⟩) (c.vert ⟨2, by decide⟩) = true := c.edge ⟨1, by decide⟩
  have he2 : H.toGraph.adj (c.vert ⟨2, by decide⟩) (c.vert ⟨3, by decide⟩) = true := c.edge ⟨2, by decide⟩
  have he3 : H.toGraph.adj (c.vert ⟨3, by decide⟩) (c.vert ⟨0, by decide⟩) = true := by
    simpa using c.edge ⟨3, by decide⟩
  have hopp : ∀ u v : Fin (2 * V), H.toGraph.adj u v = true →
      (u.val < V ∧ V ≤ v.val) ∨ (V ≤ u.val ∧ v.val < V) := by
    intro u v h
    by_cases hu : u.val < V
    · by_cases hv : V ≤ v.val
      · exact Or.inl ⟨hu, hv⟩
      · simp [toGraph, hu, hv] at h
    · by_cases hv : v.val < V
      · exact Or.inr ⟨by omega, hv⟩
      · simp [toGraph, hu, hv] at h
  rcases hopp _ _ he0 with ⟨h0, h1⟩ | ⟨h0, h1⟩
  · have h2 : (c.vert ⟨2, by decide⟩).val < V := by
      rcases hopp _ _ he1 with ⟨ha, _⟩ | ⟨_, hb⟩ <;> omega
    have h3 : V ≤ (c.vert ⟨3, by decide⟩).val := by
      rcases hopp _ _ he2 with ⟨_, hb⟩ | ⟨ha, _⟩ <;> omega
    have hp_ne : (⟨(c.vert ⟨0, by decide⟩).val, h0⟩ : Fin V) ≠ ⟨(c.vert ⟨2, by decide⟩).val, h2⟩ := by
      intro heq
      have hv : (c.vert ⟨0, by decide⟩).val = (c.vert ⟨2, by decide⟩).val :=
        congrArg (fun x : Fin V => x.val) heq
      have hi := congrArg Fin.val (c.inj ⟨0, by decide⟩ ⟨2, by decide⟩ (Fin.ext hv))
      dsimp at hi; omega
    have hb_ne : (⟨(c.vert ⟨1, by decide⟩).val - V, by omega⟩ : Fin V) ≠
        ⟨(c.vert ⟨3, by decide⟩).val - V, by omega⟩ := by
      intro heq
      have hv0 : (c.vert ⟨1, by decide⟩).val - V = (c.vert ⟨3, by decide⟩).val - V :=
        congrArg (fun x : Fin V => x.val) heq
      have hv : (c.vert ⟨1, by decide⟩).val = (c.vert ⟨3, by decide⟩).val := by omega
      have hi := congrArg Fin.val (c.inj ⟨1, by decide⟩ ⟨3, by decide⟩ (Fin.ext hv))
      dsimp at hi; omega
    exact H.linear _ _ _ _ hb_ne hp_ne
      (toGraph_adj_inc_pt_blk H _ _ h0 h1 he0)
      (toGraph_adj_inc_blk_pt H _ _ h1 h2 he1)
      (toGraph_adj_inc_blk_pt H _ _ h3 h0 he3)
      (toGraph_adj_inc_pt_blk H _ _ h2 h3 he2)
  · have h2 : V ≤ (c.vert ⟨2, by decide⟩).val := by
      rcases hopp _ _ he1 with ⟨_, hb⟩ | ⟨ha, _⟩ <;> omega
    have h3 : (c.vert ⟨3, by decide⟩).val < V := by
      rcases hopp _ _ he2 with ⟨ha, _⟩ | ⟨_, hb⟩ <;> omega
    have hp_ne : (⟨(c.vert ⟨1, by decide⟩).val, h1⟩ : Fin V) ≠ ⟨(c.vert ⟨3, by decide⟩).val, h3⟩ := by
      intro heq
      have hv : (c.vert ⟨1, by decide⟩).val = (c.vert ⟨3, by decide⟩).val :=
        congrArg (fun x : Fin V => x.val) heq
      have hi := congrArg Fin.val (c.inj ⟨1, by decide⟩ ⟨3, by decide⟩ (Fin.ext hv))
      dsimp at hi; omega
    have hb_ne : (⟨(c.vert ⟨0, by decide⟩).val - V, by omega⟩ : Fin V) ≠
        ⟨(c.vert ⟨2, by decide⟩).val - V, by omega⟩ := by
      intro heq
      have hv0 : (c.vert ⟨0, by decide⟩).val - V = (c.vert ⟨2, by decide⟩).val - V :=
        congrArg (fun x : Fin V => x.val) heq
      have hv : (c.vert ⟨0, by decide⟩).val = (c.vert ⟨2, by decide⟩).val := by omega
      have hi := congrArg Fin.val (c.inj ⟨0, by decide⟩ ⟨2, by decide⟩ (Fin.ext hv))
      dsimp at hi; omega
    exact H.linear _ _ _ _ hb_ne hp_ne
      (toGraph_adj_inc_blk_pt H _ _ h0 h1 he0)
      (toGraph_adj_inc_pt_blk H _ _ h3 h0 he3)
      (toGraph_adj_inc_pt_blk H _ _ h1 h2 he1)
      (toGraph_adj_inc_blk_pt H _ _ h2 h3 he2)

/-! ### 3. Zero-Oracle Witness Soundness (`C6`, `C8`, `C16`) -/

/-- **Master Alternating Cycle Soundness Lemma**:
    Any `m ≥ 2` pairwise distinct points `pts : Fin m → Fin V` and `m` pairwise distinct
    blocks `blks : Fin m → Fin V` such that block `blks i` contains both `pts i` and
    `pts ((i + 1) % m)` certifies a simple cycle of length `2 * m` in `H.toGraph`! -/
theorem alternating_cycle_sound (H : CubicBipConfig V) (m : Nat) (hm : 2 ≤ m)
    (pts blks : Fin m → Fin V)
    (hpts_inj : ∀ i j : Fin m, pts i = pts j → i = j)
    (hblks_inj : ∀ i j : Fin m, blks i = blks j → i = j)
    (hinc1 : ∀ i : Fin m, H.inc (pts i) (blks i) = true)
    (hinc2 : ∀ i : Fin m, H.inc (pts ⟨(i.val + 1) % m, Nat.mod_lt _ (by omega)⟩) (blks i) = true) :
    H.toGraph.HasCycle (2 * m) := by
  refine ⟨{
    hlen := by omega
    vert := fun k =>
      if k.val % 2 == 0 then ptVert (pts ⟨k.val / 2, by omega⟩)
      else blkVert (blks ⟨k.val / 2, by omega⟩)
    inj := fun i j hij => by
      by_cases hi : i.val % 2 = 0 <;> by_cases hj : j.val % 2 = 0
      · have hi' : (i.val % 2 == 0) = true := beq_iff_eq.mpr hi
        have hj' : (j.val % 2 == 0) = true := beq_iff_eq.mpr hj
        simp only [hi', hj', ↓reduceIte] at hij
        have hv : (pts ⟨i.val / 2, by omega⟩).val = (pts ⟨j.val / 2, by omega⟩).val :=
          congrArg (fun x : Fin (2 * V) => x.val) hij
        have hpeq : pts ⟨i.val / 2, by omega⟩ = pts ⟨j.val / 2, by omega⟩ := Fin.ext hv
        have hd := congrArg Fin.val (hpts_inj _ _ hpeq)
        dsimp only at hd
        exact Fin.ext (by omega)
      · have hi' : (i.val % 2 == 0) = true := beq_iff_eq.mpr hi
        have hj' : (j.val % 2 == 0) = false := beq_false_of_ne hj
        simp only [hi', hj', Bool.false_eq_true, ↓reduceIte] at hij
        have hv : (pts ⟨i.val / 2, by omega⟩).val = V + (blks ⟨j.val / 2, by omega⟩).val :=
          congrArg (fun x : Fin (2 * V) => x.val) hij
        have := (pts ⟨i.val / 2, by omega⟩).isLt
        omega
      · have hi' : (i.val % 2 == 0) = false := beq_false_of_ne hi
        have hj' : (j.val % 2 == 0) = true := beq_iff_eq.mpr hj
        simp only [hi', hj', Bool.false_eq_true, ↓reduceIte] at hij
        have hv : V + (blks ⟨i.val / 2, by omega⟩).val = (pts ⟨j.val / 2, by omega⟩).val :=
          congrArg (fun x : Fin (2 * V) => x.val) hij
        have := (pts ⟨j.val / 2, by omega⟩).isLt
        omega
      · have hi' : (i.val % 2 == 0) = false := beq_false_of_ne hi
        have hj' : (j.val % 2 == 0) = false := beq_false_of_ne hj
        simp only [hi', hj', Bool.false_eq_true, ↓reduceIte] at hij
        have hv : V + (blks ⟨i.val / 2, by omega⟩).val = V + (blks ⟨j.val / 2, by omega⟩).val :=
          congrArg (fun x : Fin (2 * V) => x.val) hij
        have hbeq : blks ⟨i.val / 2, by omega⟩ = blks ⟨j.val / 2, by omega⟩ := Fin.ext (by omega)
        have hd := congrArg Fin.val (hblks_inj _ _ hbeq)
        dsimp only at hd
        exact Fin.ext (by omega)
    edge := fun k => by
      by_cases hk : k.val % 2 = 0
      · have hk' : (k.val % 2 == 0) = true := beq_iff_eq.mpr hk
        have hnxt_mod : (k.val + 1) % (2 * m) = k.val + 1 := Nat.mod_eq_of_lt (by omega)
        have hnxt_odd : ((k.val + 1) % (2 * m) % 2 == 0) = false :=
          beq_false_of_ne (by rw [hnxt_mod]; omega)
        have hdiv : (k.val + 1) % (2 * m) / 2 = k.val / 2 := by rw [hnxt_mod]; omega
        simp only [hk', hnxt_odd, Bool.false_eq_true, ↓reduceIte]
        have hfin : (⟨(k.val + 1) % (2 * m) / 2, by omega⟩ : Fin m) = ⟨k.val / 2, by omega⟩ :=
          Fin.ext hdiv
        rw [hfin, toGraph_adj_pt_blk]
        exact hinc1 ⟨k.val / 2, by omega⟩
      · have hk' : (k.val % 2 == 0) = false := beq_false_of_ne hk
        have hnxt_even : ((k.val + 1) % (2 * m) % 2 == 0) = true := by
          apply beq_iff_eq.mpr
          by_cases hlt : k.val + 1 < 2 * m
          · rw [Nat.mod_eq_of_lt hlt]; omega
          · have heq : k.val + 1 = 2 * m := by omega
            rw [heq, Nat.mod_self]
        have hdiv : (k.val + 1) % (2 * m) / 2 = (k.val / 2 + 1) % m := by
          by_cases hlt : k.val + 1 < 2 * m
          · have hm1 : k.val / 2 + 1 < m := by omega
            rw [Nat.mod_eq_of_lt hlt, Nat.mod_eq_of_lt hm1]; omega
          · have heq : k.val + 1 = 2 * m := by omega
            have hd : k.val / 2 + 1 = m := by omega
            rw [heq, Nat.mod_self, hd, Nat.mod_self]
        simp only [hk', hnxt_even, Bool.false_eq_true, ↓reduceIte]
        have hfin : (⟨(k.val + 1) % (2 * m) / 2, by rw [hdiv]; exact Nat.mod_lt _ (by omega)⟩ : Fin m) =
            ⟨(k.val / 2 + 1) % m, Nat.mod_lt _ (by omega)⟩ := Fin.ext hdiv
        rw [hfin, toGraph_adj_blk_pt]
        exact hinc2 ⟨k.val / 2, by omega⟩
  }⟩

/-- **Zero-Oracle `check_c6` Soundness** (matching `cubic_bipartite_girth10_cert_verify.cpp::check_c6`):
    2 distinct witness blocks + candidate block forming a 3-point triangle certifies `HasCycle 6`. -/
theorem check_c6_witness_sound (H : CubicBipConfig V)
    (pts blks : Fin 3 → Fin V)
    (hpts : ∀ i j, pts i = pts j → i = j)
    (hblks : ∀ i j, blks i = blks j → i = j)
    (h1 : ∀ i, H.inc (pts i) (blks i) = true)
    (h2 : ∀ i, H.inc (pts ⟨(i.val + 1) % 3, Nat.mod_lt _ (by omega)⟩) (blks i) = true) :
    H.toGraph.HasCycle 6 :=
  alternating_cycle_sound H 3 (by omega) pts blks hpts hblks h1 h2

/-- **Zero-Oracle `check_c8` Soundness** (matching `cubic_bipartite_cert_verify.cpp::check_c8`
    and `cubic_bipartite_parallel.cpp::check_c8`):
    3 distinct witness blocks + candidate block on 4 distinct intersection points certifies `HasCycle 8`. -/
theorem check_c8_witness_sound (H : CubicBipConfig V)
    (pts blks : Fin 4 → Fin V)
    (hpts : ∀ i j, pts i = pts j → i = j)
    (hblks : ∀ i j, blks i = blks j → i = j)
    (h1 : ∀ i, H.inc (pts i) (blks i) = true)
    (h2 : ∀ i, H.inc (pts ⟨(i.val + 1) % 4, Nat.mod_lt _ (by omega)⟩) (blks i) = true) :
    H.toGraph.HasCycle 8 :=
  alternating_cycle_sound H 4 (by omega) pts blks hpts hblks h1 h2

/-- **Zero-Oracle `check_c16` Soundness** (matching `check_c16` in both zero-oracle verifiers):
    7 distinct witness blocks + candidate block on 8 distinct points certifies `HasCycle 16`. -/
theorem check_c16_witness_sound (H : CubicBipConfig V)
    (pts blks : Fin 8 → Fin V)
    (hpts : ∀ i j, pts i = pts j → i = j)
    (hblks : ∀ i j, blks i = blks j → i = j)
    (h1 : ∀ i, H.inc (pts i) (blks i) = true)
    (h2 : ∀ i, H.inc (pts ⟨(i.val + 1) % 8, Nat.mod_lt _ (by omega)⟩) (blks i) = true) :
    H.toGraph.HasCycle 16 :=
  alternating_cycle_sound H 8 (by omega) pts blks hpts hblks h1 h2

/-! ### 4. Lossless Branch A Root Dichotomy (`Orbit 1: {0,4,6}` vs `Orbit 2: {0,6,7}`) -/

/-- **Lossless `C6` Two-Orbit Root Theorem (`c6_two_orbit_dichotomy`)**:
    In ANY `CubicBipConfig V` containing a Berge-triangle (`C6`) formed by 3 distinct blocks
    `b0 = {a0, a1, x0}`, `b1 = {a1, a2, x1}`, `b2 = {a0, a2, x2}` on 6 pairwise distinct points,
    there exists a 3rd block `b3` incident to `a0` (`b3 ≠ b0, b3 ≠ b2`) whose two remaining
    distinct points `{y, z}` are completely disjoint from `{a0, a1, a2, x0, x2}`, leaving
    EXACTLY two exhaustive orbits:
      - **Orbit 1 (`{0, 4, 6}`)**: `y = x1` and `z ∉ {a0, a1, a2, x0, x1, x2}`, OR
      - **Orbit 2 (`{0, 6, 7}`)**: both `y, z ∉ {a0, a1, a2, x0, x1, x2}`. -/
theorem c6_two_orbit_dichotomy (H : CubicBipConfig V)
    (a0 a1 a2 x0 x1 x2 b0 b1 b2 : Fin V)
    (_hb01 : b0 ≠ b1) (hb02 : b0 ≠ b2) (_hb12 : b1 ≠ b2)
    (_ha01 : a0 ≠ a1) (_ha02 : a0 ≠ a2) (_ha12 : a1 ≠ a2)
    (_ha0x0 : a0 ≠ x0) (_ha0x1 : a0 ≠ x1) (_ha0x2 : a0 ≠ x2)
    (hb0_inc : H.inc a0 b0 = true ∧ H.inc a1 b0 = true ∧ H.inc x0 b0 = true)
    (_hb1_inc : H.inc a1 b1 = true ∧ H.inc a2 b1 = true ∧ H.inc x1 b1 = true)
    (hb2_inc : H.inc a0 b2 = true ∧ H.inc a2 b2 = true ∧ H.inc x2 b2 = true) :
    ∃ (b3 y z : Fin V),
      b3 ≠ b0 ∧ b3 ≠ b2 ∧
      H.inc a0 b3 = true ∧ H.inc y b3 = true ∧ H.inc z b3 = true ∧
      y ≠ a0 ∧ z ≠ a0 ∧ y ≠ z ∧
      y ≠ a1 ∧ y ≠ a2 ∧ y ≠ x0 ∧ y ≠ x2 ∧
      z ≠ a1 ∧ z ≠ a2 ∧ z ≠ x0 ∧ z ≠ x2 ∧
      ((y = x1 ∧ z ≠ x1) ∨ (y ≠ x1 ∧ z ≠ x1)) := by
  obtain ⟨i0, hi0⟩ := (H.pointBlks_iff a0 b0).mp hb0_inc.1
  obtain ⟨i2, hi2⟩ := (H.pointBlks_iff a0 b2).mp hb2_inc.1
  have hi02 : i0 ≠ i2 := fun h => hb02 (hi0.symm.trans (congrArg (H.pointBlks a0) h |>.trans hi2))
  have hex_i3 : ∃ i3 : Fin 3, i3 ≠ i0 ∧ i3 ≠ i2 := by
    have hall : ∀ u v : Fin 3, u ≠ v → ∃ w : Fin 3, w ≠ u ∧ w ≠ v := by decide
    exact hall i0 i2 hi02
  obtain ⟨i3, hi30, hi32⟩ := hex_i3
  let b3 := H.pointBlks a0 i3
  have hb3_a0 : H.inc a0 b3 = true := (H.pointBlks_iff a0 b3).mpr ⟨i3, rfl⟩
  have hb30 : b3 ≠ b0 := fun h => hi30 (H.pointBlks_inj a0 i3 i0 (h.trans hi0.symm))
  have hb32 : b3 ≠ b2 := fun h => hi32 (H.pointBlks_inj a0 i3 i2 (h.trans hi2.symm))
  obtain ⟨j0, hj0⟩ := (H.blockPts_iff b3 a0).mp hb3_a0
  have hex_j12 : ∃ j1 j2 : Fin 3, j1 ≠ j0 ∧ j2 ≠ j0 ∧ j1 ≠ j2 := by
    have hall : ∀ u : Fin 3, ∃ v w : Fin 3, v ≠ u ∧ w ≠ u ∧ v ≠ w := by decide
    exact hall j0
  obtain ⟨j1, j2, hj10, hj20, hj12⟩ := hex_j12
  let p := H.blockPts b3 j1
  let q := H.blockPts b3 j2
  have hp_inc : H.inc p b3 = true := (H.blockPts_iff b3 p).mpr ⟨j1, rfl⟩
  have hq_inc : H.inc q b3 = true := (H.blockPts_iff b3 q).mpr ⟨j2, rfl⟩
  have hpa0 : p ≠ a0 := fun h => hj10 (H.blockPts_inj b3 j1 j0 (h.trans hj0.symm))
  have hqa0 : q ≠ a0 := fun h => hj20 (H.blockPts_inj b3 j2 j0 (h.trans hj0.symm))
  have hpq : p ≠ q := fun h => hj12 (H.blockPts_inj b3 j1 j2 h)
  have havoid : ∀ w : Fin V, H.inc w b3 = true → w ≠ a0 →
      w ≠ a1 ∧ w ≠ a2 ∧ w ≠ x0 ∧ w ≠ x2 := by
    intro w hwb3 hwa0
    refine ⟨?_, ?_, ?_, ?_⟩
    · intro h; subst h; exact H.linear b3 b0 a0 w hb30 hwa0.symm hb3_a0 hwb3 hb0_inc.1 hb0_inc.2.1
    · intro h; subst h; exact H.linear b3 b2 a0 w hb32 hwa0.symm hb3_a0 hwb3 hb2_inc.1 hb2_inc.2.1
    · intro h; subst h; exact H.linear b3 b0 a0 w hb30 hwa0.symm hb3_a0 hwb3 hb0_inc.1 hb0_inc.2.2
    · intro h; subst h; exact H.linear b3 b2 a0 w hb32 hwa0.symm hb3_a0 hwb3 hb2_inc.1 hb2_inc.2.2
  obtain ⟨hpa1, hpa2, hpx0, hpx2⟩ := havoid p hp_inc hpa0
  obtain ⟨hqa1, hqa2, hqx0, hqx2⟩ := havoid q hq_inc hqa0
  by_cases hpx1 : p = x1
  · exact ⟨b3, p, q, hb30, hb32, hb3_a0, hp_inc, hq_inc, hpa0, hqa0, hpq,
      hpa1, hpa2, hpx0, hpx2, hqa1, hqa2, hqx0, hqx2,
      Or.inl ⟨hpx1, fun h => hpq (hpx1.trans h.symm)⟩⟩
  · by_cases hqx1 : q = x1
    · exact ⟨b3, q, p, hb30, hb32, hb3_a0, hq_inc, hp_inc, hqa0, hpa0, hpq.symm,
        hqa1, hqa2, hqx0, hqx2, hpa1, hpa2, hpx0, hpx2,
        Or.inl ⟨hqx1, hpx1⟩⟩
    · exact ⟨b3, p, q, hb30, hb32, hb3_a0, hp_inc, hq_inc, hpa0, hqa0, hpq,
        hpa1, hpa2, hpx0, hpx2, hqa1, hqa2, hqx0, hqx2,
        Or.inr ⟨hpx1, hqx1⟩⟩

/-! ### 5. Lossless Branch B Moore-Tree Lower Bound (`62 ≤ N`, i.e., `31 + 31` Moore Tree) -/

/-- A non-backtracking walk of length `d` in `G`. -/
structure NBWalk {n : Nat} (G : FinGraph n) (d : Nat) where
  vert : Fin (d + 1) → Fin n
  edge : ∀ i : Fin d, G.adj (vert ⟨i.val, by omega⟩) (vert ⟨i.val + 1, by omega⟩) = true
  noback : ∀ i : Nat, (hi : i + 2 ≤ d) → vert ⟨i + 2, by omega⟩ ≠ vert ⟨i, by omega⟩

/-- In a graph of girth `≥ 10`, ANY non-backtracking walk of length `1 ≤ d ≤ 9` has
    `vert d ≠ vert 0`. -/
theorem nbwalk_endpoints_ne_of_girth10 {n : Nat} {G : FinGraph n}
    (hg10 : ∀ L : Nat, L < 10 → ¬ G.HasCycle L) :
    ∀ (d : Nat), 1 ≤ d → d ≤ 9 → ∀ (w : NBWalk G d),
      w.vert ⟨d, by omega⟩ ≠ w.vert ⟨0, by omega⟩ := by
  intro d
  induction d using Nat.strongRecOn with
  | ind d ih =>
    intro hd1 hd9 w heq
    by_cases hd1_eq : d = 1
    · subst hd1_eq
      have he := w.edge ⟨0, by omega⟩
      rw [heq, G.loopless] at he
      cases he
    · by_cases hd2_eq : d = 2
      · subst hd2_eq
        exact w.noback 0 (by omega) heq
      · have hd3 : 3 ≤ d := by omega
        by_cases hinj : ∀ i j : Fin d, w.vert ⟨i.val, by omega⟩ = w.vert ⟨j.val, by omega⟩ → i = j
        · have hcyc : G.SimpleCycle d := {
            hlen := hd3
            vert := fun i => w.vert ⟨i.val, by omega⟩
            inj := hinj
            edge := fun i => by
              by_cases hlast : i.val + 1 < d
              · have hm : (i.val + 1) % d = i.val + 1 := Nat.mod_eq_of_lt hlast
                simpa [hm] using w.edge i
              · have hi_eq : i.val + 1 = d := by omega
                have hm : (i.val + 1) % d = 0 := by rw [hi_eq, Nat.mod_self]
                have he := w.edge i
                have hfin : (⟨i.val + 1, by omega⟩ : Fin (d + 1)) = ⟨d, by omega⟩ := Fin.ext hi_eq
                rw [hfin, heq] at he
                simpa [hm] using he
          }
          exact hg10 d (by omega) ⟨hcyc⟩
        · have hex : ∃ a b : Fin d, a.val < b.val ∧
              w.vert ⟨a.val, by omega⟩ = w.vert ⟨b.val, by omega⟩ := by
            exact Classical.byContradiction fun hno => hinj fun i j hij => by
              by_cases h1 : i.val < j.val
              · exact absurd ⟨i, j, h1, hij⟩ hno
              · by_cases h2 : j.val < i.val
                · exact absurd ⟨j, i, h2, hij.symm⟩ hno
                · exact Fin.ext (by omega)
          obtain ⟨a, b, hab, hveq⟩ := hex
          let sub : NBWalk G (b.val - a.val) := {
            vert := fun t => w.vert ⟨a.val + t.val, by omega⟩
            edge := fun t => by
              have he := w.edge ⟨a.val + t.val, by omega⟩
              simpa [Nat.add_assoc] using he
            noback := fun i hi => by
              have hnb := w.noback (a.val + i) (by omega)
              simpa [Nat.add_assoc] using hnb
          }
          have hsub_eq : sub.vert ⟨b.val - a.val, by omega⟩ = sub.vert ⟨0, by omega⟩ := by
            have h1 : a.val + (b.val - a.val) = b.val := by omega
            have h2 : a.val + 0 = a.val := Nat.add_zero _
            simpa [sub, h1, h2] using hveq.symm
          exact ih (b.val - a.val) (by omega) (by omega) (by omega) sub hsub_eq

/-- Top-level helper: evaluate a node `(endpoint, parent)` in the edge-rooted Moore tree. -/
private def mooreEval {N : Nat} (ch : Fin N → Fin N → Bool → Fin N)
    (u0 v0 : Fin N) (side : Bool) : List Bool → Fin N × Fin N
  | [] => if side then (v0, u0) else (u0, v0)
  | b :: rest =>
    let cur := mooreEval ch u0 v0 side rest
    (ch cur.1 cur.2 b, cur.1)

/-- Top-level helper: leaf-to-root vertex list of a node in the edge-rooted Moore tree. -/
private def mooreWalk {N : Nat} (ch : Fin N → Fin N → Bool → Fin N)
    (u0 v0 : Fin N) (side : Bool) : List Bool → List (Fin N)
  | [] => [if side then v0 else u0]
  | b :: rest => (mooreEval ch u0 v0 side (b :: rest)).1 :: mooreWalk ch u0 v0 side rest

private theorem mooreWalk_length {N : Nat} (ch : Fin N → Fin N → Bool → Fin N)
    (u0 v0 : Fin N) (side : Bool) (p : List Bool) :
    (mooreWalk ch u0 v0 side p).length = p.length + 1 := by
  induction p with
  | nil => rfl
  | cons b r ih => simp [mooreWalk, ih]

private theorem getElem_eq_of_idx {α : Type} (xs : List α) {i j : Nat}
    (hi : i < xs.length) (hj : j < xs.length) (h : i = j) :
    xs[i]'hi = xs[j]'hj := by
  subst h; rfl

private theorem getElem_eq_of_eq {α : Type} {xs ys : List α} (hl : xs = ys) {i j : Nat}
    (hi : i < xs.length) (hj : j < ys.length) (h : i = j) :
    xs[i]'hi = ys[j]'hj := by
  subst hl; subst h; rfl

private theorem mooreWalk_elem_drop {N : Nat} (ch : Fin N → Fin N → Bool → Fin N)
    (u0 v0 : Fin N) (side : Bool) (a r : List Bool) (k : Nat) (hk : k ≤ a.length) :
    (mooreWalk ch u0 v0 side (a ++ r))[k]' (by rw [mooreWalk_length, List.length_append]; omega) =
      (mooreEval ch u0 v0 side (a.drop k ++ r)).1 := by
  induction a generalizing k with
  | nil =>
    have hk0 : k = 0 := by simp at hk; omega
    subst hk0
    cases r with
    | nil => cases side <;> rfl
    | cons _ _ => rfl
  | cons b a' ih =>
    cases k with
    | zero => rfl
    | succ k =>
      simp only [List.cons_append, mooreWalk, List.getElem_cons_succ, List.drop_succ_cons]
      exact ih k (by simp at hk; omega)

/-- **Moore Tree Lower Bound for Girth-`≥ 10` Cubic Graphs (`girth10_moore_tree_62`)**:
    Every finite simple 3-regular graph `B : CubicBase N` of girth `≥ 10` (`N ≥ 1`) has
    at least **`62`** vertices (`31` on each side of a root edge `(u0, v0)` — justifying
    the lossless 15-block / 31-point Moore tree of Stage 2C Branch B)! -/
theorem girth10_moore_tree_62 {N : Nat} (B : CubicBase N) (hpos : 0 < N)
    (hg10 : ∀ L : Nat, L < 10 → ¬ B.graph.HasCycle L) :
    62 ≤ N := by
  have pick2 : ∀ (u prev : Fin N), ∃ c0 c1 : Fin N,
      B.graph.adj u c0 = true ∧ B.graph.adj u c1 = true ∧
      c0 ≠ prev ∧ c1 ≠ prev ∧ c0 ≠ c1 := by
    intro u prev
    have hex : ∃ a b : Fin 3, a ≠ b ∧ B.nbr u a ≠ prev ∧ B.nbr u b ≠ prev := by
      by_cases h0 : B.nbr u ⟨0, by decide⟩ = prev
      · refine ⟨⟨1, by decide⟩, ⟨2, by decide⟩, by decide, ?_, ?_⟩
        · intro h; have := B.nbr_inj u _ _ (h.trans h0.symm); exact absurd (congrArg Fin.val this) (by decide)
        · intro h; have := B.nbr_inj u _ _ (h.trans h0.symm); exact absurd (congrArg Fin.val this) (by decide)
      · by_cases h1 : B.nbr u ⟨1, by decide⟩ = prev
        · refine ⟨⟨0, by decide⟩, ⟨2, by decide⟩, by decide, h0, ?_⟩
          intro h; have := B.nbr_inj u _ _ (h.trans h1.symm); exact absurd (congrArg Fin.val this) (by decide)
        · exact ⟨⟨0, by decide⟩, ⟨1, by decide⟩, by decide, h0, h1⟩
    obtain ⟨a, b, hab, ha, hb⟩ := hex
    exact ⟨B.nbr u a, B.nbr u b,
      (B.nbr_adj u _).mpr ⟨a, rfl⟩, (B.nbr_adj u _).mpr ⟨b, rfl⟩,
      ha, hb, fun h => hab (B.nbr_inj u a b h)⟩
  let ch (u prev : Fin N) (b : Bool) : Fin N :=
    if b then (Classical.choose (pick2 u prev))
    else (Classical.choose (Classical.choose_spec (pick2 u prev)))
  have hch_adj : ∀ u prev b, B.graph.adj u (ch u prev b) = true := by
    intro u prev b
    have hsp := Classical.choose_spec (Classical.choose_spec (pick2 u prev))
    cases b <;> simp only [ch, ↓reduceIte, Bool.false_eq_true]
    · exact hsp.2.1
    · exact hsp.1
  have hch_ne_prev : ∀ u prev b, ch u prev b ≠ prev := by
    intro u prev b
    have hsp := Classical.choose_spec (Classical.choose_spec (pick2 u prev))
    cases b <;> simp only [ch, ↓reduceIte, Bool.false_eq_true]
    · exact hsp.2.2.2.1
    · exact hsp.2.2.1
  have hch_inj : ∀ u prev, ch u prev false ≠ ch u prev true := by
    intro u prev
    have hsp := Classical.choose_spec (Classical.choose_spec (pick2 u prev))
    exact hsp.2.2.2.2.symm
  let u0 : Fin N := ⟨0, hpos⟩
  let v0 : Fin N := B.nbr u0 ⟨0, by decide⟩
  have huv_adj : B.graph.adj u0 v0 = true := (B.nbr_adj u0 v0).mpr ⟨⟨0, by decide⟩, rfl⟩
  have huv_ne : u0 ≠ v0 := fun h => by
    rw [h, B.graph.loopless] at huv_adj; cases huv_adj
  let isNB (xs : List (Fin N)) : Prop :=
    (∀ i : Nat, (hi : i + 1 < xs.length) →
      B.graph.adj (xs[i]' (by omega)) (xs[i + 1]' hi) = true) ∧
    (∀ i : Nat, (hi : i + 2 < xs.length) →
      xs[i + 2]' hi ≠ xs[i]' (by omega))
  have hnb_ne : ∀ (xs : List (Fin N)) (h2 : 2 ≤ xs.length), xs.length ≤ 10 → isNB xs →
      xs[xs.length - 1]' (by omega) ≠ xs[0]' (by omega) := by
    intro xs h2 h10 ⟨he, hnb⟩
    let d := xs.length - 1
    have hd1 : 1 ≤ d := by omega
    have hd9 : d ≤ 9 := by omega
    let w : NBWalk B.graph d := {
      vert := fun t => xs[t.val]' (by have := t.isLt; omega)
      edge := fun i => he i.val (by have := i.isLt; omega)
      noback := fun i hi => hnb i (by omega)
    }
    exact nbwalk_endpoints_ne_of_girth10 hg10 d hd1 hd9 w
  have heval_props : ∀ s p,
      B.graph.adj (mooreEval ch u0 v0 s p).2 (mooreEval ch u0 v0 s p).1 = true ∧
      isNB (mooreWalk ch u0 v0 s p) ∧
      (∀ (hi : 1 < (mooreWalk ch u0 v0 s p).length),
        (mooreWalk ch u0 v0 s p)[1]' hi = (mooreEval ch u0 v0 s p).2) ∧
      ((mooreWalk ch u0 v0 s p)[(mooreWalk ch u0 v0 s p).length - 1]'
        (by rw [mooreWalk_length]; omega) = if s then v0 else u0) := by
    intro s p
    induction p with
    | nil =>
      refine ⟨?_, ⟨fun i hi => by simp [mooreWalk] at hi, fun i hi => by simp [mooreWalk] at hi⟩,
        fun hi => by simp [mooreWalk] at hi, by cases s <;> rfl⟩
      cases s
      · simpa [mooreEval, B.graph.symm] using huv_adj
      · simpa [mooreEval] using huv_adj
    | cons b r ih =>
      obtain ⟨_, ⟨he_r, hnb_r⟩, hsec_r, hlast_r⟩ := ih
      have hlen_r := mooreWalk_length ch u0 v0 s r
      have hadj_top : B.graph.adj (mooreEval ch u0 v0 s r).1
          (ch (mooreEval ch u0 v0 s r).1 (mooreEval ch u0 v0 s r).2 b) = true :=
        hch_adj _ _ _
      have hne_prev : ch (mooreEval ch u0 v0 s r).1 (mooreEval ch u0 v0 s r).2 b ≠
          (mooreEval ch u0 v0 s r).2 :=
        hch_ne_prev _ _ _
      have h0_r : (mooreWalk ch u0 v0 s r)[0]' (by omega) = (mooreEval ch u0 v0 s r).1 := by
        cases r with
        | nil => cases s <;> rfl
        | cons _ _ => rfl
      refine ⟨hadj_top, ⟨?_, ?_⟩, ?_, ?_⟩
      · intro i hi
        cases i with
        | zero =>
          simp only [mooreWalk, List.getElem_cons_zero, List.getElem_cons_succ, mooreEval]
          rw [h0_r, B.graph.symm]; exact hadj_top
        | succ i =>
          simp only [mooreWalk, List.getElem_cons_succ]
          exact he_r i (by simp [mooreWalk] at hi; omega)
      · intro i hi
        cases i with
        | zero =>
          simp only [mooreWalk, List.getElem_cons_zero, List.getElem_cons_succ, mooreEval]
          have h1r : 1 < (mooreWalk ch u0 v0 s r).length := by simp [mooreWalk] at hi; omega
          rw [hsec_r h1r]
          exact hne_prev.symm
        | succ i =>
          simp only [mooreWalk, List.getElem_cons_succ]
          exact hnb_r i (by simp [mooreWalk] at hi; omega)
      · intro hi
        simp only [mooreWalk, List.getElem_cons_succ, mooreEval]
        exact h0_r
      · simp only [mooreWalk]
        rw [getElem_eq_of_idx _ _ (by simp [List.length_cons]; omega)
          (show ((mooreEval ch u0 v0 s (b :: r)).1 :: mooreWalk ch u0 v0 s r).length - 1 =
            (mooreWalk ch u0 v0 s r).length - 1 + 1 by simp [List.length_cons]; omega)]
        rw [List.getElem_cons_succ]
        exact hlast_r
  have hisNB_rev : ∀ xs, isNB xs → isNB xs.reverse := by
    intro xs ⟨he, hnb⟩
    refine ⟨fun i hi => ?_, fun i hi => ?_⟩
    · simp only [List.length_reverse] at hi
      simp only [List.getElem_reverse]
      rw [B.graph.symm]
      have h1 := he (xs.length - 1 - (i + 1)) (by omega)
      rw [getElem_eq_of_idx xs _ (by omega) (show xs.length - 1 - i = xs.length - 1 - (i + 1) + 1 by omega)]
      exact h1
    · simp only [List.length_reverse] at hi
      simp only [List.getElem_reverse]
      have h1 := hnb (xs.length - 1 - (i + 2)) (by omega)
      rw [getElem_eq_of_idx xs _ (by omega) (show xs.length - 1 - i = xs.length - 1 - (i + 2) + 2 by omega)]
      intro h; exact h1 h.symm
  have hisNB_append : ∀ (xs ys : List (Fin N)) (hx : 1 ≤ xs.length) (hy : 1 ≤ ys.length),
      isNB xs → isNB ys →
      B.graph.adj (xs[xs.length - 1]' (by omega)) (ys[0]' (by omega)) = true →
      (∀ (h2 : 2 ≤ xs.length), ys[0]' (by omega) ≠ xs[xs.length - 2]' (by omega)) →
      (∀ (h2 : 2 ≤ ys.length), ys[1]' (by omega) ≠ xs[xs.length - 1]' (by omega)) →
      isNB (xs ++ ys) := by
    intro xs ys hx hy ⟨hex, hnbx⟩ ⟨hey, hnby⟩ hbridge hnb1 hnb2
    refine ⟨fun i hi => ?_, fun i hi => ?_⟩
    · simp only [List.length_append] at hi
      by_cases h1 : i + 1 < xs.length
      · rw [List.getElem_append_left (by omega), List.getElem_append_left h1]
        exact hex i h1
      · by_cases h2 : i < xs.length
        · rw [List.getElem_append_left h2, List.getElem_append_right (by omega)]
          rw [getElem_eq_of_idx xs _ (by omega) (show i = xs.length - 1 by omega),
              getElem_eq_of_idx ys _ (by omega) (show i + 1 - xs.length = 0 by omega)]
          exact hbridge
        · rw [List.getElem_append_right (by omega), List.getElem_append_right (by omega)]
          rw [getElem_eq_of_idx ys _ (by omega) (show i + 1 - xs.length = (i - xs.length) + 1 by omega)]
          exact hey (i - xs.length) (by omega)
    · simp only [List.length_append] at hi
      by_cases h1 : i + 2 < xs.length
      · rw [List.getElem_append_left h1, List.getElem_append_left (by omega)]
        exact hnbx i h1
      · by_cases h2 : i + 1 < xs.length
        · rw [List.getElem_append_right (by omega), List.getElem_append_left (by omega)]
          rw [getElem_eq_of_idx xs _ (by omega) (show i = xs.length - 2 by omega),
              getElem_eq_of_idx ys _ (by omega) (show i + 2 - xs.length = 0 by omega)]
          exact hnb1 (by omega)
        · by_cases h3 : i < xs.length
          · rw [List.getElem_append_right (by omega), List.getElem_append_left h3]
            rw [getElem_eq_of_idx xs _ (by omega) (show i = xs.length - 1 by omega),
                getElem_eq_of_idx ys _ (by omega) (show i + 2 - xs.length = 1 by omega)]
            exact hnb2 (by omega)
          · rw [List.getElem_append_right (by omega), List.getElem_append_right (by omega)]
            rw [getElem_eq_of_idx ys _ (by omega) (show i + 2 - xs.length = (i - xs.length) + 2 by omega)]
            exact hnby (i - xs.length) (by omega)
  have hroot_avoid : ∀ s p (hp : 2 ≤ (mooreWalk ch u0 v0 s p).length),
      (mooreWalk ch u0 v0 s p)[(mooreWalk ch u0 v0 s p).length - 2]' (by omega) ≠
        (if s then u0 else v0) := by
    intro s p
    induction p with
    | nil => intro hp; simp [mooreWalk] at hp
    | cons b r ih =>
      intro hp
      cases r with
      | nil =>
        simp only [mooreWalk, List.length_cons, List.length_nil]
        have hne := hch_ne_prev (if s then v0 else u0) (if s then u0 else v0) b
        cases s <;> simpa [mooreEval] using hne
      | cons b2 r2 =>
        have hlen := mooreWalk_length ch u0 v0 s (b2 :: r2)
        have hlen_r2 := mooreWalk_length ch u0 v0 s r2
        have hpos2 : 2 ≤ (mooreWalk ch u0 v0 s (b2 :: r2)).length := by
          rw [hlen, List.length_cons]; omega
        have h1 := ih hpos2
        simp only [mooreWalk] at h1 ⊢
        rw [getElem_eq_of_idx _ _ (by simp [List.length_cons]; omega)
          (show ((mooreEval ch u0 v0 s (b :: b2 :: r2)).1 ::
              (mooreEval ch u0 v0 s (b2 :: r2)).1 :: mooreWalk ch u0 v0 s r2).length - 2 =
            ((mooreEval ch u0 v0 s (b2 :: r2)).1 :: mooreWalk ch u0 v0 s r2).length - 2 + 1
            by simp only [List.length_cons, hlen_r2]; omega)]
        rw [List.getElem_cons_succ]
        exact h1
  have htake_nb : ∀ (xs : List (Fin N)) (m : Nat), isNB xs → isNB (xs.take m) := by
    intro xs m ⟨hex, hnbx⟩
    refine ⟨fun i hi => ?_, fun i hi => ?_⟩
    · have hm : i + 1 < xs.length := by simp at hi; omega
      simpa [List.getElem_take] using hex i hm
    · have hm : i + 2 < xs.length := by simp at hi; omega
      simpa [List.getElem_take] using hnbx i hm
  have hsuf_dich : ∀ (u v : List Bool), u ≠ v →
      (∃ a : List Bool, a ≠ [] ∧ u = a ++ v) ∨
      (∃ a : List Bool, a ≠ [] ∧ v = a ++ u) ∨
      (∃ (a1 a2 r : List Bool) (b1 b2 : Bool), b1 ≠ b2 ∧
        u = a1 ++ (b1 :: r) ∧ v = a2 ++ (b2 :: r)) := by
    have hpref : ∀ (x y : List Bool), x ≠ y →
        (∃ a : List Bool, a ≠ [] ∧ x = y ++ a) ∨
        (∃ a : List Bool, a ≠ [] ∧ y = x ++ a) ∨
        (∃ (r a1 a2 : List Bool) (b1 b2 : Bool), b1 ≠ b2 ∧
          x = r ++ (b1 :: a1) ∧ y = r ++ (b2 :: a2)) := by
      intro x
      induction x with
      | nil =>
        intro y hne
        exact Or.inr (Or.inl ⟨y, hne.symm, by simp⟩)
      | cons hx xs ihx =>
        intro y hne
        cases y with
        | nil => exact Or.inl ⟨hx :: xs, List.cons_ne_nil hx xs, by simp⟩
        | cons hy ys =>
          by_cases hb : hx = hy
          · subst hb
            have hxy : xs ≠ ys := fun h => hne (by rw [h])
            rcases ihx ys hxy with ⟨a, ha, hxeq⟩ | ⟨a, ha, hyeq⟩ | ⟨r, a1, a2, b1, b2, h12, hxeq, hyeq⟩
            · exact Or.inl ⟨a, ha, by simp [hxeq]⟩
            · exact Or.inr (Or.inl ⟨a, ha, by simp [hyeq]⟩)
            · exact Or.inr (Or.inr ⟨hx :: r, a1, a2, b1, b2, h12, by simp [hxeq], by simp [hyeq]⟩)
          · exact Or.inr (Or.inr ⟨[], xs, ys, hx, hy, hb, rfl, rfl⟩)
    intro u v hne
    have hrev_ne : u.reverse ≠ v.reverse := fun h => hne (by simpa using congrArg List.reverse h)
    rcases hpref u.reverse v.reverse hrev_ne with
      ⟨a, ha, heq'⟩ | ⟨a, ha, heq'⟩ | ⟨r, a1, a2, b1, b2, h12, heq1, heq2⟩
    · refine Or.inl ⟨a.reverse, fun h => ha (by simpa using congrArg List.reverse h), ?_⟩
      have := congrArg List.reverse heq'; simpa using this
    · refine Or.inr (Or.inl ⟨a.reverse, fun h => ha (by simpa using congrArg List.reverse h), ?_⟩)
      have := congrArg List.reverse heq'; simpa using this
    · refine Or.inr (Or.inr ⟨a1.reverse, a2.reverse, r.reverse, b1, b2, h12, ?_, ?_⟩)
      · have := congrArg List.reverse heq1; simpa [List.append_assoc] using this
      · have := congrArg List.reverse heq2; simpa [List.append_assoc] using this
  -- Injectivity of `mooreEval` on all 62 addresses `(side, path)` with `path.length ≤ 4`!
  have hinj_tree : ∀ (s1 s2 : Bool) (p1 p2 : List Bool),
      p1.length ≤ 4 → p2.length ≤ 4 →
      (mooreEval ch u0 v0 s1 p1).1 = (mooreEval ch u0 v0 s2 p2).1 → s1 = s2 ∧ p1 = p2 := by
    intro s1 s2 p1 p2 h1 h2 heq
    by_cases hs : s1 = s2
    · subst hs
      by_cases hpeq : p1 = p2
      · exact ⟨rfl, hpeq⟩
      · exfalso
        rcases hsuf_dich p1 p2 hpeq with ⟨a, ha, hp1_eq⟩ | ⟨a, ha, hp2_eq⟩ |
            ⟨a1, a2, r, b1, b2, hb12, hp1_eq, hp2_eq⟩
        · subst hp1_eq
          have halen : 1 ≤ a.length := List.length_pos_iff.mpr ha
          let ws := (mooreWalk ch u0 v0 s1 (a ++ p2)).take (a.length + 1)
          have hws_len : ws.length = a.length + 1 := by
            simp only [ws, List.length_take, mooreWalk_length, List.length_append]
            omega
          have hws_nb : isNB ws := htake_nb _ _ (heval_props s1 (a ++ p2)).2.1
          have hne_end := hnb_ne ws (by omega) (by simp at h1; omega) hws_nb
          have h0w : ws[0]' (by omega) = (mooreEval ch u0 v0 s1 (a ++ p2)).1 := by
            simp only [ws, List.getElem_take]
            exact mooreWalk_elem_drop ch u0 v0 s1 a p2 0 (by omega)
          have hlw : ws[ws.length - 1]' (by omega) = (mooreEval ch u0 v0 s1 p2).1 := by
            simp only [ws, List.getElem_take, hws_len, Nat.add_sub_cancel]
            simpa [List.drop_length] using mooreWalk_elem_drop ch u0 v0 s1 a p2 a.length (Nat.le_refl _)
          rw [h0w, hlw] at hne_end
          exact hne_end heq.symm
        · subst hp2_eq
          have halen : 1 ≤ a.length := List.length_pos_iff.mpr ha
          let ws := (mooreWalk ch u0 v0 s1 (a ++ p1)).take (a.length + 1)
          have hws_len : ws.length = a.length + 1 := by
            simp only [ws, List.length_take, mooreWalk_length, List.length_append]
            omega
          have hws_nb : isNB ws := htake_nb _ _ (heval_props s1 (a ++ p1)).2.1
          have hne_end := hnb_ne ws (by omega) (by simp at h2; omega) hws_nb
          have h0w : ws[0]' (by omega) = (mooreEval ch u0 v0 s1 (a ++ p1)).1 := by
            simp only [ws, List.getElem_take]
            exact mooreWalk_elem_drop ch u0 v0 s1 a p1 0 (by omega)
          have hlw : ws[ws.length - 1]' (by omega) = (mooreEval ch u0 v0 s1 p1).1 := by
            simp only [ws, List.getElem_take, hws_len, Nat.add_sub_cancel]
            simpa [List.drop_length] using mooreWalk_elem_drop ch u0 v0 s1 a p1 a.length (Nat.le_refl _)
          rw [h0w, hlw] at hne_end
          exact hne_end heq
        · subst hp1_eq; subst hp2_eq
          have ha1 : a1.length + 1 ≤ 4 := by simp at h1; omega
          have ha2 : a2.length + 1 ≤ 4 := by simp at h2; omega
          let w1 := (mooreWalk ch u0 v0 s1 (a1 ++ (b1 :: r))).take (a1.length + 2)
          let w2raw := (mooreWalk ch u0 v0 s1 (a2 ++ (b2 :: r))).take (a2.length + 1)
          let w2 := w2raw.reverse
          have hw1_len : w1.length = a1.length + 2 := by
            simp only [w1, List.length_take, mooreWalk_length, List.length_append, List.length_cons]
            omega
          have hw2raw_len : w2raw.length = a2.length + 1 := by
            simp only [w2raw, List.length_take, mooreWalk_length, List.length_append, List.length_cons]
            omega
          have hw2_len : w2.length = a2.length + 1 := by simp [w2, hw2raw_len]
          have hw1_nb : isNB w1 := htake_nb _ _ (heval_props s1 _).2.1
          have hw2_nb : isNB w2 := hisNB_rev _ (htake_nb _ _ (heval_props s1 _).2.1)
          have hw1_last : w1[w1.length - 1]' (by omega) = (mooreEval ch u0 v0 s1 r).1 := by
            have hidx : w1.length - 1 = (a1 ++ [b1]).length := by
              rw [hw1_len, List.length_append, List.length_cons, List.length_nil]; omega
            have hrew : mooreWalk ch u0 v0 s1 (a1 ++ b1 :: r) =
                mooreWalk ch u0 v0 s1 ((a1 ++ [b1]) ++ r) :=
              congrArg (mooreWalk ch u0 v0 s1) (by rw [List.append_assoc]; rfl)
            simp only [w1, List.getElem_take]
            have hte := mooreWalk_elem_drop ch u0 v0 s1 (a1 ++ [b1]) r (a1 ++ [b1]).length (Nat.le_refl _)
            rw [List.drop_length, List.nil_append] at hte
            rw [← hte]
            exact getElem_eq_of_eq hrew _ _ hidx
          have hw1_pen : w1[w1.length - 2]' (by omega) =
              ch (mooreEval ch u0 v0 s1 r).1 (mooreEval ch u0 v0 s1 r).2 b1 := by
            have hidx : w1.length - 2 = a1.length := by omega
            simp only [w1, List.getElem_take]
            rw [getElem_eq_of_idx _ _ (by rw [mooreWalk_length, List.length_append, List.length_cons]; omega) hidx]
            simpa [List.drop_length, mooreEval] using
              mooreWalk_elem_drop ch u0 v0 s1 a1 (b1 :: r) a1.length (Nat.le_refl _)
          have hw2_first : w2[0]' (by omega) =
              ch (mooreEval ch u0 v0 s1 r).1 (mooreEval ch u0 v0 s1 r).2 b2 := by
            simp only [w2, List.getElem_reverse, w2raw, List.getElem_take]
            rw [getElem_eq_of_idx _ _ (by rw [mooreWalk_length, List.length_append, List.length_cons]; omega)
              (show w2raw.length - 1 - 0 = a2.length by omega)]
            simpa [List.drop_length, mooreEval] using
              mooreWalk_elem_drop ch u0 v0 s1 a2 (b2 :: r) a2.length (Nat.le_refl _)
          have hbridge : B.graph.adj (w1[w1.length - 1]' (by omega)) (w2[0]' (by omega)) = true := by
            rw [hw1_last, hw2_first]; exact hch_adj _ _ _
          have hcomb : isNB (w1 ++ w2) := by
            apply hisNB_append w1 w2 (by omega) (by omega) hw1_nb hw2_nb hbridge
            · intro _
              rw [hw2_first, hw1_pen]
              cases b1 <;> cases b2
              · exact absurd rfl hb12
              · exact (hch_inj _ _).symm
              · exact hch_inj _ _
              · exact absurd rfl hb12
            · intro h2y
              have ha2pos : 1 ≤ a2.length := by omega
              rw [hw1_last]
              simp only [w2, List.getElem_reverse, w2raw, List.getElem_take]
              rw [getElem_eq_of_idx _ _ (by rw [mooreWalk_length, List.length_append, List.length_cons]; omega)
                (show w2raw.length - 1 - 1 = a2.length - 1 by omega)]
              rw [mooreWalk_elem_drop ch u0 v0 s1 a2 (b2 :: r) (a2.length - 1) (by omega)]
              have hdrop_len : (a2.drop (a2.length - 1)).length = 1 := by simp; omega
              cases hdrop : a2.drop (a2.length - 1) with
              | nil => rw [hdrop] at hdrop_len; simp at hdrop_len
              | cons blast rest =>
                rw [hdrop] at hdrop_len
                have hrest : rest = [] := List.eq_nil_of_length_eq_zero (by rw [List.length_cons] at hdrop_len; omega)
                subst hrest
                simp only [List.singleton_append, mooreEval]
                exact hch_ne_prev _ _ _
          have hw_len_2 : 2 ≤ (w1 ++ w2).length := by rw [List.length_append, hw1_len, hw2_len]; omega
          have hw_len_10 : (w1 ++ w2).length ≤ 10 := by rw [List.length_append, hw1_len, hw2_len]; omega
          have hne_end := hnb_ne (w1 ++ w2) hw_len_2 hw_len_10 hcomb
          have hstart : (w1 ++ w2)[0]' (by omega) =
              (mooreEval ch u0 v0 s1 (a1 ++ b1 :: r)).1 := by
            rw [List.getElem_append_left (by omega)]
            simp only [w1, List.getElem_take]
            exact mooreWalk_elem_drop ch u0 v0 s1 a1 (b1 :: r) 0 (by omega)
          have hend : (w1 ++ w2)[(w1 ++ w2).length - 1]' (by omega) =
              (mooreEval ch u0 v0 s1 (a2 ++ b2 :: r)).1 := by
            rw [List.getElem_append_right (by rw [List.length_append, hw1_len, hw2_len]; omega)]
            simp only [w2, List.getElem_reverse, w2raw, List.getElem_take]
            rw [getElem_eq_of_idx _ _ (by rw [mooreWalk_length, List.length_append, List.length_cons]; omega)
              (show w2raw.length - 1 - ((w1 ++ w2).length - 1 - w1.length) = 0 by
                rw [List.length_append, hw1_len, hw2_len, hw2raw_len]; omega)]
            exact mooreWalk_elem_drop ch u0 v0 s1 a2 (b2 :: r) 0 (by omega)
          rw [hstart, hend] at hne_end
          exact hne_end heq.symm
    · -- Opposite sides `s1 ≠ s2`: concatenate `mooreWalk s1 p1 ++ (mooreWalk s2 p2).reverse`!
      exfalso
      let xs1 := mooreWalk ch u0 v0 s1 p1
      let xs2 := (mooreWalk ch u0 v0 s2 p2).reverse
      obtain ⟨_, hnb1, _, hlast1⟩ := heval_props s1 p1
      obtain ⟨_, hnb2, _, hlast2⟩ := heval_props s2 p2
      have hlen1 : xs1.length = p1.length + 1 := mooreWalk_length ch u0 v0 s1 p1
      have hlen2raw : (mooreWalk ch u0 v0 s2 p2).length = p2.length + 1 := mooreWalk_length ch u0 v0 s2 p2
      have hlen2 : xs2.length = p2.length + 1 := by simp [xs2, hlen2raw]
      have hnb2r : isNB xs2 := hisNB_rev _ hnb2
      have hbridge : B.graph.adj (xs1[xs1.length - 1]' (by omega))
          (xs2[0]' (by omega)) = true := by
        have h1e : xs1[xs1.length - 1]' (by omega) = (if s1 then v0 else u0) := hlast1
        have h2e : xs2[0]' (by omega) = (if s2 then v0 else u0) := by
          simp only [xs2, List.getElem_reverse, Nat.sub_zero]; exact hlast2
        rw [h1e, h2e]
        cases s1 <;> cases s2
        · exact absurd rfl hs
        · exact huv_adj
        · rw [B.graph.symm]; exact huv_adj
        · exact absurd rfl hs
      have hcomb : isNB (xs1 ++ xs2) := by
        apply hisNB_append xs1 xs2 (by omega) (by omega) hnb1 hnb2r hbridge
        · intro h2x
          have h2e : xs2[0]' (by omega) = (if s2 then v0 else u0) := by
            simp only [xs2, List.getElem_reverse, Nat.sub_zero]; exact hlast2
          rw [h2e]
          have hne := hroot_avoid s1 p1 h2x
          cases s1 <;> cases s2
          · exact absurd rfl hs
          · exact hne.symm
          · exact hne.symm
          · exact absurd rfl hs
        · intro h2y
          have h1e : xs1[xs1.length - 1]' (by omega) = (if s1 then v0 else u0) := hlast1
          rw [h1e]
          have hlen2' : 2 ≤ (mooreWalk ch u0 v0 s2 p2).length := by omega
          have hne := hroot_avoid s2 p2 hlen2'
          have h2y' : xs2[1]' h2y =
              (mooreWalk ch u0 v0 s2 p2)[(mooreWalk ch u0 v0 s2 p2).length - 2]' (by omega) := by
            simp only [xs2, List.getElem_reverse]
            exact getElem_eq_of_idx _ _ (by omega) (by omega)
          rw [h2y']
          cases s1 <;> cases s2
          · exact absurd rfl hs
          · exact hne
          · exact hne
          · exact absurd rfl hs
      have hxs_len_2 : 2 ≤ (xs1 ++ xs2).length := by rw [List.length_append, hlen1, hlen2]; omega
      have hxs_len_10 : (xs1 ++ xs2).length ≤ 10 := by rw [List.length_append, hlen1, hlen2]; omega
      have hne_end := hnb_ne (xs1 ++ xs2) hxs_len_2 hxs_len_10 hcomb
      have hstart : (xs1 ++ xs2)[0]' (by omega) = (mooreEval ch u0 v0 s1 p1).1 := by
        rw [List.getElem_append_left (by omega)]
        cases p1 with
        | nil => cases s1 <;> rfl
        | cons _ _ => rfl
      have hend : (xs1 ++ xs2)[(xs1 ++ xs2).length - 1]' (by omega) =
          (mooreEval ch u0 v0 s2 p2).1 := by
        rw [List.getElem_append_right (by rw [List.length_append, hlen1, hlen2]; omega)]
        simp only [xs2, List.getElem_reverse]
        rw [getElem_eq_of_idx _ _ (by omega)
          (show (mooreWalk ch u0 v0 s2 p2).length - 1 - ((xs1 ++ xs2).length - 1 - xs1.length) = 0 by
            rw [List.length_append, hlen1, hlen2, hlen2raw]; omega)]
        cases p2 with
        | nil => cases s2 <;> rfl
        | cons _ _ => rfl
      rw [hstart, hend] at hne_end
      exact hne_end heq.symm
  let paths4 : List (List Bool) :=
    let l0 : List (List Bool) := [[]]
    let l1 := l0.flatMap (fun p => [false :: p, true :: p])
    let l2 := l1.flatMap (fun p => [false :: p, true :: p])
    let l3 := l2.flatMap (fun p => [false :: p, true :: p])
    let l4 := l3.flatMap (fun p => [false :: p, true :: p])
    l0 ++ l1 ++ l2 ++ l3 ++ l4
  let addrs62 : List (Bool × List Bool) :=
    paths4.map (fun p => (false, p)) ++ paths4.map (fun p => (true, p))
  have hlen62 : addrs62.length = 62 := by decide
  have hnd62 : addrs62.Nodup := by decide
  have hplen : ∀ a ∈ addrs62, a.2.length ≤ 4 := by decide
  have hinj62 : ∀ a ∈ addrs62, ∀ b ∈ addrs62,
      (mooreEval ch u0 v0 a.1 a.2).1 = (mooreEval ch u0 v0 b.1 b.2).1 → a = b := by
    intro a ha b hb heq
    obtain ⟨hs, hp⟩ := hinj_tree a.1 b.1 a.2 b.2 (hplen a ha) (hplen b hb) heq
    cases a; cases b; simp only at hs hp; subst hs; subst hp; rfl
  have hnd_img : ∀ (xs : List (Bool × List Bool)), xs.Nodup → (∀ a ∈ xs, a ∈ addrs62) →
      (xs.map (fun a => (mooreEval ch u0 v0 a.1 a.2).1)).Nodup := by
    intro xs
    induction xs with
    | nil => intro _ _; simp
    | cons x xs ih =>
      intro hnd hsub
      rw [List.nodup_cons] at hnd
      simp only [List.map_cons, List.nodup_cons, List.mem_map]
      refine ⟨?_, ih hnd.2 (fun y hy => hsub y (List.mem_cons_of_mem x hy))⟩
      rintro ⟨y, hy, heq⟩
      have hxy := hinj62 y (hsub y (List.mem_cons_of_mem x hy)) x (hsub x (List.mem_cons_self ..)) heq
      exact hnd.1 (hxy ▸ hy)
  have hnd_fin := hnd_img addrs62 hnd62 (fun _ h => h)
  have hle : (addrs62.map (fun a => (mooreEval ch u0 v0 a.1 a.2).1)).length ≤ (List.finRange N).length := by
    have aux : ∀ {α : Type} [DecidableEq α] (xs ys : List α), xs.Nodup →
        (∀ x, x ∈ xs → x ∈ ys) → xs.length ≤ ys.length := by
      intro α _ xs
      induction xs with
      | nil => intro _ _ _; simp
      | cons x xs ih =>
        intro ys hnd hsub
        rw [List.nodup_cons] at hnd
        have hx : x ∈ ys := hsub x (List.mem_cons_self ..)
        have hsub' : ∀ z, z ∈ xs → z ∈ ys.erase x := fun z hz =>
          (List.mem_erase_of_ne (fun h => by subst h; exact hnd.1 hz)).mpr (hsub z (List.mem_cons_of_mem x hz))
        have hle1 := ih (ys.erase x) hnd.2 hsub'
        have herase : (ys.erase x).length + 1 = ys.length := by
          rw [List.length_erase_of_mem hx]
          have hpos' : 0 < ys.length := List.length_pos_of_mem hx
          omega
        simp only [List.length_cons]; omega
    exact aux _ _ hnd_fin (fun z _ => List.mem_finRange z)
  simp only [List.length_map, List.length_finRange, hlen62] at hle
  exact hle

end CubicBipConfig
end Sglab
