import Sglab.Graph
import Sglab.GadgetLift
import Sglab.Gadgets
import Sglab.Records
import Sglab.Stage1Extensions
import Sglab.UnconditionalF6Data

/-!
# Sglab.UnconditionalF6 — Unconditional Kernel-Verified `f_cubic(6) ≤ 10,498`

Proves **unconditionally** inside the pure Lean 4 kernel (zero Mathlib, zero `sorry`,
zero custom axioms, zero `native_decide`):
  1. `k3_g16_n702Base : CubicBase 702`: the House of Graphs 702-vertex cubic bipartite
     graph `k3_g16_n702.g6` is a valid simple 3-regular bipartite graph.
  2. `k3_g16_n702_girth16 : ∀ L < 16, ¬ k3_g16_n702Base.graph.HasCycle L`:
     proved via TWO kernel-verified graph automorphisms (`auto0`, `auto1`) generating a
     single transitive orbit on the 351-vertex `true` bipartition class, combined with
     ONE Tree-Ball BFS certificate of depth 7 rooted at vertex `1`!
  3. `f_cubic_6_le_10498`:
     `∃ G : FinGraph 10498, G.IsCubic ∧ ¬ G.HasCycle 4 ∧ ¬ G.HasCycle 8 ∧ ¬ G.HasCycle 16 ∧ ¬ G.HasCycle 32 ∧ ¬ G.HasCycle 64`.
-/

namespace Sglab
open FinGraph
open Sglab.F6Data

/-! ### 1. Kernel-Fast Structural Depth-10 Universal Range Checker (`allPow2` / `allBelow`) -/

def allPow2 : Nat → Nat → (Nat → Bool) → Bool
  | 0, lo, p => p lo
  | d + 1, lo, p => allPow2 d lo p && allPow2 d (lo + 2 ^ d) p

theorem allPow2_sound (d lo : Nat) (p : Nat → Bool) (h : allPow2 d lo p = true) :
    ∀ i : Nat, lo ≤ i → i < lo + 2 ^ d → p i = true := by
  induction d generalizing lo with
  | zero =>
    simp only [allPow2, Nat.pow_zero] at h ⊢
    intro i h1 h2
    have : i = lo := by omega
    subst this; exact h
  | succ d ih =>
    simp only [allPow2, Bool.and_eq_true] at h
    have hpow : 2 ^ (d + 1) = 2 ^ d + 2 ^ d := by rw [Nat.pow_succ]; omega
    intro i h1 h2
    by_cases hlt : i < lo + 2 ^ d
    · exact ih lo h.1 i h1 hlt
    · exact ih (lo + 2 ^ d) h.2 i (by omega) (by omega)

def allBelow (k : Nat) (p : Nat → Bool) : Bool :=
  decide (k ≤ 1024) && allPow2 10 0 (fun i => if decide (i < k) then p i else true)

theorem allBelow_sound (k : Nat) (p : Nat → Bool) (h : allBelow k p = true) :
    ∀ i : Nat, i < k → p i = true := by
  simp only [allBelow, Bool.and_eq_true, decide_eq_true_eq] at h
  intro i hi
  have h1 := allPow2_sound 10 0 _ h.2 i (Nat.zero_le i) (by have : 2 ^ 10 = 1024 := rfl; omega)
  simpa [hi] using h1

/-! ### 2. `CubicBase 702` Construction for `k3_g16_n702.g6` -/

private def adj702 (u : Nat) : Nat × Nat × Nat := adjTree.get u

private def checkBase702 (u : Nat) : Bool :=
  let t := adj702 u
  let a := t.1
  let b := t.2.1
  let c := t.2.2
  (decide (a < 702)) && (decide (b < 702)) && (decide (c < 702)) &&
  (a != u) && (b != u) && (c != u) &&
  (a != b) && (a != c) && (b != c) &&
  tripleHas (adj702 a) u &&
  tripleHas (adj702 b) u &&
  tripleHas (adj702 c) u

private theorem checkBase702_ok : allBelow 702 checkBase702 = true := rfl

private theorem base702_prop (u : Fin 702) :
    let t := adj702 u.val
    (t.1 < 702 ∧ t.2.1 < 702 ∧ t.2.2 < 702) ∧
    (t.1 ≠ u.val ∧ t.2.1 ≠ u.val ∧ t.2.2 ≠ u.val) ∧
    (t.1 ≠ t.2.1 ∧ t.1 ≠ t.2.2 ∧ t.2.1 ≠ t.2.2) ∧
    (tripleHas (adj702 t.1) u.val = true ∧
     tripleHas (adj702 t.2.1) u.val = true ∧
     tripleHas (adj702 t.2.2) u.val = true) := by
  have h := allBelow_sound 702 checkBase702 checkBase702_ok u.val u.isLt
  simp only [checkBase702, Bool.and_eq_true, decide_eq_true_eq, bne_iff_ne] at h
  obtain ⟨⟨⟨⟨⟨⟨⟨⟨⟨⟨⟨h1, h2⟩, h3⟩, h4⟩, h5⟩, h6⟩, h7⟩, h8⟩, h9⟩, h10⟩, h11⟩, h12⟩ := h
  exact ⟨⟨h1, h2, h3⟩, ⟨h4, h5, h6⟩, ⟨h7, h8, h9⟩, ⟨h10, h11, h12⟩⟩

def k3_g16_n702Base : CubicBase 702 where
  graph := {
    adj := fun u v => tripleHas (adj702 u.val) v.val
    symm := fun u v => by
      have imp : ∀ x y : Fin 702,
          tripleHas (adj702 x.val) y.val = true → tripleHas (adj702 y.val) x.val = true := by
        intro x y hxy
        have hp := (base702_prop x).2.2.2
        simp only [tripleHas, Bool.or_eq_true, beq_iff_eq] at hxy
        rcases hxy with (heq | heq) | heq
        · rw [← heq]; exact hp.1
        · rw [← heq]; exact hp.2.1
        · rw [← heq]; exact hp.2.2
      cases h1 : tripleHas (adj702 u.val) v.val <;> cases h2 : tripleHas (adj702 v.val) u.val
      · rfl
      · exact absurd (imp v u h2) (by rw [h1]; decide)
      · exact absurd (imp u v h1) (by rw [h2]; decide)
      · rfl
    loopless := fun u => by
      have hp := (base702_prop u).2.1
      cases h : tripleHas (adj702 u.val) u.val
      · rfl
      · simp only [tripleHas, Bool.or_eq_true, beq_iff_eq] at h
        rcases h with (heq | heq) | heq
        · exact absurd heq hp.1
        · exact absurd heq hp.2.1
        · exact absurd heq hp.2.2
  }
  nbr := fun u k =>
    ⟨tripleNbr (adj702 u.val) k, by
      have hb := (base702_prop u).1
      have hk : k.val = 0 ∨ k.val = 1 ∨ k.val = 2 := by omega
      rcases hk with h | h | h
      · have hk0 : k = ⟨0, by decide⟩ := Fin.ext h; subst hk0; exact hb.1
      · have hk1 : k = ⟨1, by decide⟩ := Fin.ext h; subst hk1; exact hb.2.1
      · have hk2 : k = ⟨2, by decide⟩ := Fin.ext h; subst hk2; exact hb.2.2⟩
  nbr_inj := fun u a b heq => by
    have hd := (base702_prop u).2.2.1
    have hv : tripleNbr (adj702 u.val) a = tripleNbr (adj702 u.val) b := congrArg Fin.val heq
    have ha : a.val = 0 ∨ a.val = 1 ∨ a.val = 2 := by omega
    have hb : b.val = 0 ∨ b.val = 1 ∨ b.val = 2 := by omega
    rcases ha with ha | ha | ha <;> rcases hb with hb | hb | hb
    · exact Fin.ext (by omega)
    · have ha0 : a = ⟨0, by decide⟩ := Fin.ext ha; subst ha0
      have hb1 : b = ⟨1, by decide⟩ := Fin.ext hb; subst hb1
      exact absurd hv hd.1
    · have ha0 : a = ⟨0, by decide⟩ := Fin.ext ha; subst ha0
      have hb2 : b = ⟨2, by decide⟩ := Fin.ext hb; subst hb2
      exact absurd hv hd.2.1
    · have ha1 : a = ⟨1, by decide⟩ := Fin.ext ha; subst ha1
      have hb0 : b = ⟨0, by decide⟩ := Fin.ext hb; subst hb0
      exact absurd hv.symm hd.1
    · exact Fin.ext (by omega)
    · have ha1 : a = ⟨1, by decide⟩ := Fin.ext ha; subst ha1
      have hb2 : b = ⟨2, by decide⟩ := Fin.ext hb; subst hb2
      exact absurd hv hd.2.2
    · have ha2 : a = ⟨2, by decide⟩ := Fin.ext ha; subst ha2
      have hb0 : b = ⟨0, by decide⟩ := Fin.ext hb; subst hb0
      exact absurd hv.symm hd.2.1
    · have ha2 : a = ⟨2, by decide⟩ := Fin.ext ha; subst ha2
      have hb1 : b = ⟨1, by decide⟩ := Fin.ext hb; subst hb1
      exact absurd hv.symm hd.2.2
    · exact Fin.ext (by omega)
  nbr_adj := fun u v => by
    change tripleHas (adj702 u.val) v.val = true ↔
      ∃ a : Fin 3, (⟨tripleNbr (adj702 u.val) a, _⟩ : Fin 702) = v
    constructor
    · intro h
      simp only [tripleHas, Bool.or_eq_true, beq_iff_eq] at h
      rcases h with (h1 | h2) | h3
      · exact ⟨⟨0, by decide⟩, Fin.ext h1⟩
      · exact ⟨⟨1, by decide⟩, Fin.ext h2⟩
      · exact ⟨⟨2, by decide⟩, Fin.ext h3⟩
    · rintro ⟨a, ha⟩
      have hv : tripleNbr (adj702 u.val) a = v.val := congrArg Fin.val ha
      have ha3 : a.val = 0 ∨ a.val = 1 ∨ a.val = 2 := by omega
      rcases ha3 with h | h | h
      · have ha0 : a = ⟨0, by decide⟩ := Fin.ext h; subst ha0
        simp only [tripleHas, Bool.or_eq_true, beq_iff_eq]; left; left; exact hv
      · have ha1 : a = ⟨1, by decide⟩ := Fin.ext h; subst ha1
        simp only [tripleHas, Bool.or_eq_true, beq_iff_eq]; left; right; exact hv
      · have ha2 : a = ⟨2, by decide⟩ := Fin.ext h; subst ha2
        simp only [tripleHas, Bool.or_eq_true, beq_iff_eq]; right; exact hv

/-- Helper: prove a property `P u v` for all adjacent pairs `(u, v)` of `k3_g16_n702Base`
    by checking only the 3 neighbors of each `u < 702`. -/
private theorem adj702_cases (u v : Fin 702)
    (h : k3_g16_n702Base.graph.adj u v = true) :
    v.val = (adj702 u.val).1 ∨ v.val = (adj702 u.val).2.1 ∨ v.val = (adj702 u.val).2.2 := by
  change tripleHas (adj702 u.val) v.val = true at h
  simp only [tripleHas, Bool.or_eq_true, beq_iff_eq] at h
  rcases h with (h1 | h2) | h3
  · exact Or.inl h1.symm
  · exact Or.inr (Or.inl h2.symm)
  · exact Or.inr (Or.inr h3.symm)

/-! ### 3. Bipartiteness of `k3_g16_n702` -/

private def col702 (u : Fin 702) : Bool := colTree.get u.val

private def checkBip702 (u : Nat) : Bool :=
  let t := adj702 u
  let cu := colTree.get u
  (colTree.get t.1 != cu) && (colTree.get t.2.1 != cu) && (colTree.get t.2.2 != cu)

private theorem checkBip702_ok : allBelow 702 checkBip702 = true := rfl

theorem k3_g16_n702_bipartite_col :
    ∀ u v : Fin 702, k3_g16_n702Base.graph.adj u v = true → col702 u ≠ col702 v := by
  intro u v huv
  have h := allBelow_sound 702 checkBip702 checkBip702_ok u.val u.isLt
  simp only [checkBip702, Bool.and_eq_true, bne_iff_ne] at h
  rcases adj702_cases u v huv with hv | hv | hv
  · intro heq; exact h.1.1 (by simpa [col702, hv] using heq.symm)
  · intro heq; exact h.1.2 (by simpa [col702, hv] using heq.symm)
  · intro heq; exact h.2 (by simpa [col702, hv] using heq.symm)

theorem k3_g16_n702_bipartite : IsBipartite k3_g16_n702Base.graph :=
  ⟨col702, k3_g16_n702_bipartite_col⟩

/-! ### 4. Graph Automorphisms & Transitive Orbit on the 351-Vertex `true` Class -/

/-- An automorphism of a `FinGraph n`. -/
structure GraphAuto {n : Nat} (G : FinGraph n) where
  toFun : Fin n → Fin n
  invFun : Fin n → Fin n
  left_inv : ∀ u : Fin n, invFun (toFun u) = u
  map_adj : ∀ u v : Fin n, G.adj u v = true → G.adj (toFun u) (toFun v) = true

def GraphAuto.id {n : Nat} (G : FinGraph n) : GraphAuto G where
  toFun := fun u => u
  invFun := fun u => u
  left_inv := fun _ => rfl
  map_adj := fun _ _ h => h

def GraphAuto.comp {n : Nat} {G : FinGraph n} (φ ψ : GraphAuto G) : GraphAuto G where
  toFun := fun u => φ.toFun (ψ.toFun u)
  invFun := fun u => ψ.invFun (φ.invFun u)
  left_inv := fun u => by simp [φ.left_inv, ψ.left_inv]
  map_adj := fun u v h => φ.map_adj _ _ (ψ.map_adj u v h)

def SimpleCycle.mapAuto {n L : Nat} {G : FinGraph n}
    (φ : GraphAuto G) (c : G.SimpleCycle L) : G.SimpleCycle L where
  hlen := c.hlen
  vert i := φ.toFun (c.vert i)
  inj i j hij := by
    apply c.inj
    have := congrArg φ.invFun hij
    simpa [φ.left_inv] using this
  edge i := φ.map_adj _ _ (c.edge i)

private def checkAuto702 (f finv : Q4 Nat) (u : Nat) : Bool :=
  let fu := f.get u
  let t := adj702 u
  (decide (fu < 702)) &&
  (decide (finv.get u < 702)) &&
  (finv.get fu == u) &&
  tripleHas (adj702 fu) (f.get t.1) &&
  tripleHas (adj702 fu) (f.get t.2.1) &&
  tripleHas (adj702 fu) (f.get t.2.2)

private theorem checkAuto0_ok : allBelow 702 (checkAuto702 g0Tree g0InvTree) = true := rfl
private theorem checkAuto1_ok : allBelow 702 (checkAuto702 g1Tree g1InvTree) = true := rfl

private def mkAuto702 (f finv : Q4 Nat)
    (hok : allBelow 702 (checkAuto702 f finv) = true) :
    GraphAuto k3_g16_n702Base.graph where
  toFun u := ⟨f.get u.val, by
    have h := allBelow_sound 702 _ hok u.val u.isLt
    simp only [checkAuto702, Bool.and_eq_true, decide_eq_true_eq] at h
    exact h.1.1.1.1.1⟩
  invFun u := ⟨finv.get u.val, by
    have h := allBelow_sound 702 _ hok u.val u.isLt
    simp only [checkAuto702, Bool.and_eq_true, decide_eq_true_eq] at h
    exact h.1.1.1.1.2⟩
  left_inv u := by
    have h := allBelow_sound 702 _ hok u.val u.isLt
    simp only [checkAuto702, Bool.and_eq_true, beq_iff_eq] at h
    exact Fin.ext h.1.1.1.2
  map_adj u v huv := by
    have h := allBelow_sound 702 _ hok u.val u.isLt
    simp only [checkAuto702, Bool.and_eq_true] at h
    change tripleHas (adj702 (f.get u.val)) (f.get v.val) = true
    rcases adj702_cases u v huv with hv | hv | hv
    · rw [hv]; exact h.1.1.2
    · rw [hv]; exact h.1.2
    · rw [hv]; exact h.2

private def auto0 : GraphAuto k3_g16_n702Base.graph := mkAuto702 g0Tree g0InvTree checkAuto0_ok
private def auto1 : GraphAuto k3_g16_n702Base.graph := mkAuto702 g1Tree g1InvTree checkAuto1_ok

private def checkOrbit702 (u : Nat) : Bool :=
  if colTree.get u then
    if u == 1 then true
    else
      let nxt := if stepTree.get u == 0 then g0Tree.get u else g1Tree.get u
      colTree.get nxt && decide (rankTree.get nxt < rankTree.get u)
  else true

private theorem checkOrbit702_ok : allBelow 702 checkOrbit702 = true := rfl

/-- Every vertex `u` in the `true` bipartition class can be mapped to root `1` by a
    composition of `auto0` and `auto1`! -/
private theorem exists_auto_to_root1 :
    ∀ (r : Nat) (u : Fin 702), col702 u = true → rankTree.get u.val ≤ r →
      ∃ φ : GraphAuto k3_g16_n702Base.graph, φ.toFun u = ⟨1, by omega⟩ := by
  intro r
  induction r with
  | zero =>
    intro u hcol hr
    by_cases hu1 : u.val = 1
    · exact ⟨GraphAuto.id _, Fin.ext hu1⟩
    · exfalso
      have h := allBelow_sound 702 checkOrbit702 checkOrbit702_ok u.val u.isLt
      simp only [checkOrbit702, col702] at hcol h
      rw [hcol] at h
      have hne : (u.val == 1) = false := beq_false_of_ne hu1
      simp only [hne, Bool.false_eq_true, ↓reduceIte, Bool.and_eq_true, decide_eq_true_eq] at h
      omega
  | succ r ih =>
    intro u hcol hr
    by_cases hu1 : u.val = 1
    · exact ⟨GraphAuto.id _, Fin.ext hu1⟩
    · have h := allBelow_sound 702 checkOrbit702 checkOrbit702_ok u.val u.isLt
      simp only [checkOrbit702, col702] at hcol h
      rw [hcol] at h
      have hne : (u.val == 1) = false := beq_false_of_ne hu1
      simp only [hne, Bool.false_eq_true, ↓reduceIte, Bool.and_eq_true, decide_eq_true_eq] at h
      by_cases hs : stepTree.get u.val = 0
      · have hs' : (stepTree.get u.val == 0) = true := beq_iff_eq.mpr hs
        simp only [hs', ↓reduceIte] at h
        have hcol_nxt : col702 (auto0.toFun u) = true := h.1
        have hr_nxt : rankTree.get (auto0.toFun u).val ≤ r := by
          have : rankTree.get (g0Tree.get u.val) < rankTree.get u.val := h.2
          change rankTree.get (g0Tree.get u.val) ≤ r
          omega
        obtain ⟨ψ, hψ⟩ := ih (auto0.toFun u) hcol_nxt hr_nxt
        exact ⟨ψ.comp auto0, hψ⟩
      · have hs' : (stepTree.get u.val == 0) = false := beq_false_of_ne hs
        simp only [hs', Bool.false_eq_true, ↓reduceIte] at h
        have hcol_nxt : col702 (auto1.toFun u) = true := h.1
        have hr_nxt : rankTree.get (auto1.toFun u).val ≤ r := by
          have : rankTree.get (g1Tree.get u.val) < rankTree.get u.val := h.2
          change rankTree.get (g1Tree.get u.val) ≤ r
          omega
        obtain ⟨ψ, hψ⟩ := ih (auto1.toFun u) hcol_nxt hr_nxt
        exact ⟨ψ.comp auto1, hψ⟩

/-! ### 5. Tree-Ball Girth Lemma & Kernel-Verified `girth(k3_g16_n702) ≥ 16` -/

private def checkDist1 (u : Nat) : Bool :=
  let du := dist1Tree.get u
  let t := adj702 u
  let okEdge (v : Nat) : Bool :=
    let dv := dist1Tree.get v
    (dv == du + 1) || (du == dv + 1)
  let okPar (v : Nat) : Bool :=
    if decide (dist1Tree.get v < du) then v == parent1Tree.get u else true
  okEdge t.1 && okEdge t.2.1 && okEdge t.2.2 &&
  (if decide (1 ≤ du ∧ du ≤ 7) then okPar t.1 && okPar t.2.1 && okPar t.2.2 else true)

private theorem checkDist1_ok : allBelow 702 checkDist1 = true := rfl
private theorem dist1_root : dist1Tree.get 1 = 0 := rfl

private theorem dist1_edge (u v : Fin 702) (huv : k3_g16_n702Base.graph.adj u v = true) :
    dist1Tree.get v.val = dist1Tree.get u.val + 1 ∨
    dist1Tree.get u.val = dist1Tree.get v.val + 1 := by
  have h := allBelow_sound 702 checkDist1 checkDist1_ok u.val u.isLt
  simp only [checkDist1, Bool.and_eq_true, Bool.or_eq_true, beq_iff_eq] at h
  rcases adj702_cases u v huv with hv | hv | hv
  · rw [hv]; exact h.1.1.1
  · rw [hv]; exact h.1.1.2
  · rw [hv]; exact h.1.2

private theorem dist1_unique_parent (u v : Fin 702)
    (huv : k3_g16_n702Base.graph.adj u v = true)
    (h1 : 1 ≤ dist1Tree.get u.val) (h7 : dist1Tree.get u.val ≤ 7)
    (hlt : dist1Tree.get v.val < dist1Tree.get u.val) :
    v.val = parent1Tree.get u.val := by
  have h := allBelow_sound 702 checkDist1 checkDist1_ok u.val u.isLt
  simp only [checkDist1, Bool.and_eq_true] at h
  have hpar := h.2
  have h17 : decide (1 ≤ dist1Tree.get u.val ∧ dist1Tree.get u.val ≤ 7) = true :=
    decide_eq_true ⟨h1, h7⟩
  simp only [h17, ↓reduceIte, Bool.and_eq_true] at hpar
  rcases adj702_cases u v huv with hv | hv | hv
  · have hlt' : decide (dist1Tree.get (adj702 u.val).1 < dist1Tree.get u.val) = true :=
      decide_eq_true (hv ▸ hlt)
    have h1' := hpar.1.1
    simp only [hlt', ↓reduceIte, beq_iff_eq] at h1'
    rw [hv]; exact h1'
  · have hlt' : decide (dist1Tree.get (adj702 u.val).2.1 < dist1Tree.get u.val) = true :=
      decide_eq_true (hv ▸ hlt)
    have h2' := hpar.1.2
    simp only [hlt', ↓reduceIte, beq_iff_eq] at h2'
    rw [hv]; exact h2'
  · have hlt' : decide (dist1Tree.get (adj702 u.val).2.2 < dist1Tree.get u.val) = true :=
      decide_eq_true (hv ▸ hlt)
    have h3' := hpar.2
    simp only [hlt', ↓reduceIte, beq_iff_eq] at h3'
    rw [hv]; exact h3'

/-- Helper: every nonempty list has an element maximizing `f : α → Nat`. -/
private theorem exists_max_fin {L : Nat} (hL : 0 < L) (f : Fin L → Nat) :
    ∃ m : Fin L, ∀ i : Fin L, f i ≤ f m := by
  have haux : ∀ (xs : List (Fin L)), xs ≠ [] → ∃ m ∈ xs, ∀ x ∈ xs, f x ≤ f m := by
    intro xs
    induction xs with
    | nil => intro h; exact absurd rfl h
    | cons a xs ih =>
      intro _
      cases xs with
      | nil => exact ⟨a, List.mem_cons_self .., fun x hx => by
          simp only [List.mem_singleton] at hx; subst hx; exact Nat.le_refl _⟩
      | cons b rest =>
        obtain ⟨m, hm, hmax⟩ := ih (List.cons_ne_nil b rest)
        by_cases hle : f a ≤ f m
        · refine ⟨m, List.mem_cons_of_mem a hm, fun x hx => ?_⟩
          rcases List.mem_cons.mp hx with rfl | hx'
          · exact hle
          · exact hmax x hx'
        · refine ⟨a, List.mem_cons_self .., fun x hx => ?_⟩
          rcases List.mem_cons.mp hx with rfl | hx'
          · exact Nat.le_refl _
          · have := hmax x hx'; omega
  have hne : List.finRange L ≠ [] := by
    intro h
    have hlen := congrArg List.length h
    simp only [List.length_finRange, List.length_nil] at hlen
    omega
  obtain ⟨m, _, hmax⟩ := haux (List.finRange L) hne
  exact ⟨m, fun i => hmax i (List.mem_finRange i)⟩

/-- **Tree-Ball Girth Lemma**: no simple cycle of length `< 16` passes through vertex `1`. -/
private theorem no_short_cycle_through_root1 {L : Nat} (hL16 : L < 16)
    (c : k3_g16_n702Base.graph.SimpleCycle L) (h0 : c.vert ⟨0, by have := c.hlen; omega⟩ = ⟨1, by omega⟩) :
    False := by
  have hL3 := c.hlen
  -- Forward distance bound: `dist1 (c.vert k) ≤ k`
  have hfwd : ∀ (k : Nat) (hk : k < L), dist1Tree.get (c.vert ⟨k, hk⟩).val ≤ k := by
    intro k
    induction k with
    | zero =>
      intro hk
      rw [h0]; exact Nat.le_of_eq dist1_root
    | succ k ih =>
      intro hk
      have h1 := ih (by omega)
      have he := c.edge ⟨k, by omega⟩
      have hm : (k + 1) % L = k + 1 := Nat.mod_eq_of_lt hk
      have he' : k3_g16_n702Base.graph.adj (c.vert ⟨k, by omega⟩) (c.vert ⟨k + 1, hk⟩) = true := by
        simpa [hm] using he
      have hd := dist1_edge _ _ he'
      omega
  -- Backward distance bound: `dist1 (c.vert (L - k)) ≤ k` for `1 ≤ k ≤ L`
  have hbwd : ∀ (k : Nat) (hk : k < L), dist1Tree.get (c.vert ⟨(L - k) % L, Nat.mod_lt _ (by omega)⟩).val ≤ k := by
    intro k
    induction k with
    | zero =>
      intro _
      have hm : (L - 0) % L = 0 := by simp
      have hfin : (⟨(L - 0) % L, Nat.mod_lt _ (by omega)⟩ : Fin L) = ⟨0, by omega⟩ := Fin.ext hm
      rw [hfin, h0]; exact Nat.le_of_eq dist1_root
    | succ k ih =>
      intro hk
      have h1 := ih (by omega)
      have he := c.edge ⟨L - (k + 1), by omega⟩
      have hm1 : (L - (k + 1)) % L = L - (k + 1) := Nat.mod_eq_of_lt (by omega)
      have hm2 : (L - (k + 1) + 1) % L = (L - k) % L := by
        congr 1; omega
      have he' : k3_g16_n702Base.graph.adj
          (c.vert ⟨(L - (k + 1)) % L, Nat.mod_lt _ (by omega)⟩)
          (c.vert ⟨(L - k) % L, Nat.mod_lt _ (by omega)⟩) = true := by
        simpa [hm1, hm2] using he
      have hd := dist1_edge _ _ he'
      omega
  -- Every vertex on `c` has `dist1 ≤ 7`!
  have hle7 : ∀ i : Fin L, dist1Tree.get (c.vert i).val ≤ 7 := by
    intro i
    by_cases hi : i.val ≤ 7
    · exact Nat.le_trans (hfwd i.val i.isLt) hi
    · have hk : L - i.val < L := by omega
      have h1 := hbwd (L - i.val) hk
      have hfin : (⟨(L - (L - i.val)) % L, Nat.mod_lt _ (by omega)⟩ : Fin L) = i :=
        Fin.ext (by dsimp; rw [show L - (L - i.val) = i.val by omega, Nat.mod_eq_of_lt i.isLt])
      rw [hfin] at h1
      omega
  -- Pick `i_max` maximizing `dist1 (c.vert i)`!
  obtain ⟨im, hmax⟩ := exists_max_fin (by omega : 0 < L) (fun i => dist1Tree.get (c.vert i).val)
  -- Show `1 ≤ dist1 (c.vert im)` using `c.vert 1`
  have hge1 : 1 ≤ dist1Tree.get (c.vert im).val := by
    have he0 := c.edge ⟨0, by omega⟩
    have hm1 : (0 + 1) % L = 1 := Nat.mod_eq_of_lt (by omega)
    have he0' : k3_g16_n702Base.graph.adj (c.vert ⟨0, by omega⟩) (c.vert ⟨1, by omega⟩) = true := by
      simpa [hm1] using he0
    have hd01 := dist1_edge _ _ he0'
    rw [h0] at hd01
    dsimp only at hd01
    have hr0 : dist1Tree.get 1 = 0 := dist1_root
    have hle := hmax ⟨1, by omega⟩
    omega
  have h7 := hle7 im
  -- Both cycle neighbors of `im` are adjacent to `c.vert im`, distinct, and have strictly smaller `dist1`!
  let ip : Fin L := ⟨(im.val + L - 1) % L, Nat.mod_lt _ (by omega)⟩
  let inxt : Fin L := ⟨(im.val + 1) % L, Nat.mod_lt _ (by omega)⟩
  have hadj_next : k3_g16_n702Base.graph.adj (c.vert im) (c.vert inxt) = true := c.edge im
  have hadj_prev : k3_g16_n702Base.graph.adj (c.vert im) (c.vert ip) = true := by
    rw [k3_g16_n702Base.graph.symm]
    have he := c.edge ip
    have hm : ((im.val + L - 1) % L + 1) % L = im.val := by
      rw [Nat.mod_add_mod, show im.val + L - 1 + 1 = im.val + L by omega,
          Nat.add_mod_right, Nat.mod_eq_of_lt im.isLt]
    simpa [ip, hm] using he
  have hlt_prev : dist1Tree.get (c.vert ip).val < dist1Tree.get (c.vert im).val := by
    have hd := dist1_edge _ _ hadj_prev
    have hm := hmax ip
    omega
  have hlt_next : dist1Tree.get (c.vert inxt).val < dist1Tree.get (c.vert im).val := by
    have hd := dist1_edge _ _ hadj_next
    have hm := hmax inxt
    omega
  have hp1 := dist1_unique_parent _ _ hadj_prev hge1 h7 hlt_prev
  have hp2 := dist1_unique_parent _ _ hadj_next hge1 h7 hlt_next
  have hveq : c.vert ip = c.vert inxt := Fin.ext (hp1.trans hp2.symm)
  have hieq : ip = inxt := c.inj ip inxt hveq
  have hv : (im.val + L - 1) % L = (im.val + 1) % L := congrArg Fin.val hieq
  by_cases hi0 : im.val = 0
  · rw [hi0, Nat.zero_add, Nat.mod_eq_of_lt (by omega), Nat.mod_eq_of_lt (by omega)] at hv; omega
  · by_cases hi1 : im.val + 1 < L
    · rw [show im.val + L - 1 = im.val - 1 + L by omega, Nat.add_mod_right,
          Nat.mod_eq_of_lt (by omega), Nat.mod_eq_of_lt hi1] at hv; omega
    · have hie : im.val = L - 1 := by omega
      rw [hie, show L - 1 + L - 1 = (L - 2) + L by omega, Nat.add_mod_right,
          Nat.mod_eq_of_lt (by omega), show L - 1 + 1 = L by omega, Nat.mod_self] at hv; omega

/-- **Theorem (`k3_g16_n702_girth16`)**: `k3_g16_n702.g6` has exact girth `≥ 16`! -/
theorem k3_g16_n702_girth16 :
    ∀ L : Nat, L < 16 → ¬ k3_g16_n702Base.graph.HasCycle L := by
  intro L hL ⟨c⟩
  have hL3 := c.hlen
  -- Since `k3_g16_n702` is bipartite and `c.vert 0` is adjacent to `c.vert 1`,
  -- one of `c.vert 0` or `c.vert 1` has `col702 = true`!
  have he0 := c.edge ⟨0, by omega⟩
  have hm1 : (0 + 1) % L = 1 := Nat.mod_eq_of_lt (by omega)
  have he0' : k3_g16_n702Base.graph.adj (c.vert ⟨0, by omega⟩) (c.vert ⟨1, by omega⟩) = true := by
    simpa [hm1] using he0
  have hdiff := k3_g16_n702_bipartite_col _ _ he0'
  have hex_true : ∃ c' : k3_g16_n702Base.graph.SimpleCycle L,
      col702 (c'.vert ⟨0, by omega⟩) = true := by
    cases h0 : col702 (c.vert ⟨0, by omega⟩)
    · cases h1 : col702 (c.vert ⟨1, by omega⟩)
      · exact absurd (h0.trans h1.symm) hdiff
      · refine ⟨c.rotate 1, ?_⟩
        simpa [SimpleCycle.rotate, Nat.mod_eq_of_lt (by omega : 1 < L)] using h1
    · exact ⟨c, h0⟩
  obtain ⟨c', hc'⟩ := hex_true
  obtain ⟨φ, hφ⟩ := exists_auto_to_root1 (rankTree.get (c'.vert ⟨0, by omega⟩).val)
    (c'.vert ⟨0, by omega⟩) hc' (Nat.le_refl _)
  exact no_short_cycle_through_root1 hL (SimpleCycle.mapAuto φ c') hφ

/-! ### 6. Source 8-Packing & Unconditional `f_cubic_6_le_10498` -/

private def checkChosen702 (u : Nat) : Bool :=
  let cu := chosenTree.get u
  let rec noCycle (t : Nat) (x : Nat) : Bool :=
    match t with
    | 0 => true
    | t + 1 =>
      let nx := chosenTree.get x
      (nx != u) && noCycle t nx
  (decide (cu < 702)) &&
  tripleHas (adj702 u) cu &&
  (cu != 10) && (cu != 402) && (cu != 469) && (cu != 296) &&
  noCycle 16 u

private theorem checkChosen702_ok : allBelow 702 checkChosen702 = true := rfl

private def chosen702 (u : Fin 702) : Fin 702 :=
  ⟨chosenTree.get u.val, by
    have h := allBelow_sound 702 checkChosen702 checkChosen702_ok u.val u.isLt
    simp only [checkChosen702, Bool.and_eq_true, decide_eq_true_eq] at h
    exact h.1.1.1.1.1.1⟩

private theorem chosen702_adj (u : Fin 702) :
    k3_g16_n702Base.graph.adj u (chosen702 u) = true := by
  have h := allBelow_sound 702 checkChosen702 checkChosen702_ok u.val u.isLt
  simp only [checkChosen702, Bool.and_eq_true] at h
  exact h.1.1.1.1.1.2

private theorem noCycle_sound (u : Fin 702) :
    ∀ (m : Nat) (x : Fin 702),
      checkChosen702.noCycle u.val m x.val = true →
      ∀ t : Nat, 1 ≤ t → t ≤ m → Nat.repeat chosen702 t x ≠ u := by
  intro m
  induction m with
  | zero => intro x _ t h1 h2; omega
  | succ m ih =>
    intro x h t h1 h2
    simp only [checkChosen702.noCycle, Bool.and_eq_true, bne_iff_ne] at h
    cases t with
    | zero => omega
    | succ t =>
      cases t with
      | zero =>
        intro heq
        exact h.1 (congrArg Fin.val heq)
      | succ t =>
        have hrec := ih (chosen702 x) h.2 (t + 1) (by omega) (by omega)
        have hstep : Nat.repeat chosen702 (t + 1 + 1) x = Nat.repeat chosen702 (t + 1) (chosen702 x) := by
          induction (t + 1) with
          | zero => rfl
          | succ k ihk =>
            show chosen702 (Nat.repeat chosen702 (k + 1) x) = chosen702 (Nat.repeat chosen702 k (chosen702 x))
            rw [ihk]
        rw [hstep]
        exact hrec

private theorem chosen702_no_dir16 (u : Fin 702) (t : Nat) (h1 : 1 ≤ t) (h16 : t ≤ 16) :
    Nat.repeat chosen702 t u ≠ u := by
  have h := allBelow_sound 702 checkChosen702 checkChosen702_ok u.val u.isLt
  simp only [checkChosen702, Bool.and_eq_true] at h
  exact noCycle_sound u 16 u h.2 t h1 h16

private def S702 : List (Fin 702) :=
  [⟨10, by omega⟩, ⟨402, by omega⟩, ⟨469, by omega⟩, ⟨296, by omega⟩]

private theorem S702_nodup : S702.Nodup := by decide

private theorem S702_src (s : Fin 702) (hs : s ∈ S702) (v : Fin 702) : chosen702 v ≠ s := by
  have h := allBelow_sound 702 checkChosen702 checkChosen702_ok v.val v.isLt
  simp only [checkChosen702, Bool.and_eq_true, bne_iff_ne] at h
  intro heq
  have hv : chosenTree.get v.val = s.val := congrArg Fin.val heq
  simp only [S702, List.mem_cons, List.not_mem_nil, or_false] at hs
  rcases hs with rfl | rfl | rfl | rfl
  · exact h.1.1.1.1.2 hv
  · exact h.1.1.1.2 hv
  · exact h.1.1.2 hv
  · exact h.1.2 hv

private def checkPot702 (pot : Q4 Nat) (u : Nat) : Bool :=
  let pu := pot.get u
  let t := adj702 u
  decide (pot.get t.1 ≤ pu + 1) &&
  decide (pot.get t.2.1 ≤ pu + 1) &&
  decide (pot.get t.2.2 ≤ pu + 1)

private theorem checkPot0_ok : allBelow 702 (checkPot702 pot0Tree) = true := rfl
private theorem checkPot1_ok : allBelow 702 (checkPot702 pot1Tree) = true := rfl
private theorem checkPot2_ok : allBelow 702 (checkPot702 pot2Tree) = true := rfl
private theorem checkPot3_ok : allBelow 702 (checkPot702 pot3Tree) = true := rfl

private theorem pot702_step (pot : Q4 Nat) (hok : allBelow 702 (checkPot702 pot) = true)
    (u v : Fin 702) (huv : k3_g16_n702Base.graph.adj u v = true) :
    pot.get v.val ≤ pot.get u.val + 1 := by
  have h := allBelow_sound 702 (checkPot702 pot) hok u.val u.isLt
  simp only [checkPot702, Bool.and_eq_true, decide_eq_true_eq] at h
  rcases adj702_cases u v huv with hv | hv | hv
  · rw [hv]; exact h.1.1
  · rw [hv]; exact h.1.2
  · rw [hv]; exact h.2

private theorem S702_pack (a : Fin 702) (ha : a ∈ S702) (b : Fin 702) (hb : b ∈ S702)
    (hne : a ≠ b) (d : Nat) (hd : d ≤ 8) :
    ¬ Nonempty (SimplePath k3_g16_n702Base.graph a b d) := by
  rintro ⟨p⟩
  simp only [S702, List.mem_cons, List.not_mem_nil, or_false] at ha hb
  rcases ha with rfl | rfl | rfl | rfl
  · have hlb := dist_lower_of_potential k3_g16_n702Base.graph (fun u => pot0Tree.get u.val)
      _ b d p rfl (pot702_step pot0Tree checkPot0_ok)
    rcases hb with rfl | rfl | rfl | rfl
    · exact hne rfl
    · dsimp only at hlb; have h9 : 9 ≤ pot0Tree.get 402 := by decide
      omega
    · dsimp only at hlb; have h9 : 9 ≤ pot0Tree.get 469 := by decide
      omega
    · dsimp only at hlb; have h9 : 9 ≤ pot0Tree.get 296 := by decide
      omega
  · have hlb := dist_lower_of_potential k3_g16_n702Base.graph (fun u => pot1Tree.get u.val)
      _ b d p rfl (pot702_step pot1Tree checkPot1_ok)
    rcases hb with rfl | rfl | rfl | rfl
    · dsimp only at hlb; have h9 : 9 ≤ pot1Tree.get 10 := by decide
      omega
    · exact hne rfl
    · dsimp only at hlb; have h9 : 9 ≤ pot1Tree.get 469 := by decide
      omega
    · dsimp only at hlb; have h9 : 9 ≤ pot1Tree.get 296 := by decide
      omega
  · have hlb := dist_lower_of_potential k3_g16_n702Base.graph (fun u => pot2Tree.get u.val)
      _ b d p rfl (pot702_step pot2Tree checkPot2_ok)
    rcases hb with rfl | rfl | rfl | rfl
    · dsimp only at hlb; have h9 : 9 ≤ pot2Tree.get 10 := by decide
      omega
    · dsimp only at hlb; have h9 : 9 ≤ pot2Tree.get 402 := by decide
      omega
    · exact hne rfl
    · dsimp only at hlb; have h9 : 9 ≤ pot2Tree.get 296 := by decide
      omega
  · have hlb := dist_lower_of_potential k3_g16_n702Base.graph (fun u => pot3Tree.get u.val)
      _ b d p rfl (pot702_step pot3Tree checkPot3_ok)
    rcases hb with rfl | rfl | rfl | rfl
    · dsimp only at hlb; have h9 : 9 ≤ pot3Tree.get 10 := by decide
      omega
    · dsimp only at hlb; have h9 : 9 ≤ pot3Tree.get 402 := by decide
      omega
    · dsimp only at hlb; have h9 : 9 ≤ pot3Tree.get 469 := by decide
      omega
    · exact hne rfl

/-- **Headline Theorem (`f_cubic_6_le_10498`) — Unconditional Kernel-Verified `f_cubic(6) ≤ 10,498`**:
    There exists a finite simple 3-regular graph on **10,498** vertices containing NO simple
    cycle of length `4`, `8`, `16`, `32`, or `64`! -/
theorem f_cubic_6_le_10498 :
    ∃ G : FinGraph 10498,
      G.IsCubic ∧
      ¬ G.HasCycle 4 ∧ ¬ G.HasCycle 8 ∧ ¬ G.HasCycle 16 ∧
      ¬ G.HasCycle 32 ∧ ¬ G.HasCycle 64 := by
  obtain ⟨hord, hcub, h4, h8, h16, h32, h64⟩ :=
    f_cubic_6_source_8packing k3_g16_n702Base k3_g16_n702_girth16
      chosen702 chosen702_adj chosen702_no_dir16
      S702 S702_nodup S702_src S702_pack
  have h10498 : liftOrder (fun u : Fin 702 => if S702.contains u then H7 else H15) = 10498 := by
    rw [hord]; exact rfl
  let G0 := liftGraph k3_g16_n702Base
    (fun u => if S702.contains u then H7 else H15)
    (fun u => rotPerm (k3_g16_n702Base.edgePort u (chosen702 u)))
  exact ⟨castGraph h10498 G0,
    castGraph_isCubic h10498 G0 hcub,
    castGraph_not_hasCycle h10498 G0 h4,
    castGraph_not_hasCycle h10498 G0 h8,
    castGraph_not_hasCycle h10498 G0 h16,
    castGraph_not_hasCycle h10498 G0 h32,
    castGraph_not_hasCycle h10498 G0 h64⟩

end Sglab
