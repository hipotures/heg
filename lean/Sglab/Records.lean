import Sglab.Graph
import Sglab.GadgetLift
import Sglab.Gadgets

/-!
# Sglab.Records — Kernel-Verified Extremal `{C4, C8, ..., C_{2^k}}`-Free Graph Records

Proves with zero `sorry`, zero custom axioms, and zero `native_decide`:
  1. `f_delta3_4_le_73`:
     `∃ G : FinGraph 73, G.MinDegAtLeast 3 ∧ ¬ G.HasCycle 4 ∧ ¬ G.HasCycle 8 ∧ ¬ G.HasCycle 16`
     (Petersen lifted by `3·H_8* + 7·H_7`).
  2. `f_delta3_4_le_73_alt`:
     `∃ G : FinGraph 73, G.MinDegAtLeast 3 ∧ ¬ G.HasCycle 4 ∧ ¬ G.HasCycle 8 ∧ ¬ G.HasCycle 16`
     (Petersen lifted by `1·U_1 + 9·H_8*`, structurally distinct witness with 9 deg-4 vertices).
  3. `f_cubic_5_le_370`:
     `∃ G : FinGraph 370, G.IsCubic ∧ ¬ G.HasCycle 4 ∧ ¬ G.HasCycle 8 ∧ ¬ G.HasCycle 16 ∧ ¬ G.HasCycle 32`
     (Tutte–Coxeter lifted by `20·H_15 + 10·H_7`).
  4. `f_delta3_5_le_345`:
     `∃ G : FinGraph 345, G.MinDegAtLeast 3 ∧ ¬ G.HasCycle 4 ∧ ¬ G.HasCycle 8 ∧ ¬ G.HasCycle 16 ∧ ¬ G.HasCycle 32`
     (Tutte–Coxeter lifted by `15·H_15 + 15·H_8*`).
  5. `f_cubic_6_4packing`:
     General 4-packing theorem: for ANY cubic base `B : CubicBase N` of girth `≥ 17`,
     lifting a greedy maximal 4-packing `P ↦ H_7` and `V \ P ↦ H_15` yields a cubic
     `{C4, C8, C16, C32, C64}`-free graph of order `15*N - 8*|P| ≤ 15*N - 8*((N + 45)/46)`
     (giving `≤ 30,360` on any `N = 2048` cubic girth-`≥ 17` base!).
-/

namespace Sglab
open FinGraph

/-! ### 1. Kernel-Fast Cubic Base Representation via `List (Nat × Nat × Nat)` -/

/-- Fetch the 3-neighbor triple for vertex `u` from a `List (Nat × Nat × Nat)`. -/
def tripleAt (adj : List (Nat × Nat × Nat)) (u : Nat) : Nat × Nat × Nat :=
  adj.getD u (0, 0, 0)

/-- Select the `k`-th neighbor (`k : Fin 3`) from a neighbor triple. -/
def tripleNbr (t : Nat × Nat × Nat) : Fin 3 → Nat
  | ⟨0, _⟩ => t.1
  | ⟨1, _⟩ => t.2.1
  | ⟨2, _⟩ => t.2.2

/-- Check if `v` appears in a neighbor triple (purely kernel-reducible!). -/
def tripleHas (t : Nat × Nat × Nat) (v : Nat) : Bool :=
  (t.1 == v) || (t.2.1 == v) || (t.2.2 == v)

/-- Build a `CubicBase n` from an explicit `List (Nat × Nat × Nat)` of 3-neighbor triples. -/
def cubicBaseOfTriples (n : Nat) (adjList : List (Nat × Nat × Nat))
    (hsym : ∀ u v : Fin n, tripleHas (tripleAt adjList u.val) v.val = tripleHas (tripleAt adjList v.val) u.val)
    (hloop : ∀ u : Fin n, tripleHas (tripleAt adjList u.val) u.val = false)
    (hbound : ∀ (u : Fin n) (k : Fin 3), tripleNbr (tripleAt adjList u.val) k < n)
    (hinj : ∀ (u : Fin n) (a b : Fin 3),
      tripleNbr (tripleAt adjList u.val) a = tripleNbr (tripleAt adjList u.val) b → a = b) :
    CubicBase n where
  graph := {
    adj := fun u v => tripleHas (tripleAt adjList u.val) v.val
    symm := hsym
    loopless := hloop
  }
  nbr := fun u k => ⟨tripleNbr (tripleAt adjList u.val) k, hbound u k⟩
  nbr_inj := fun u a b heq => hinj u a b (congrArg Fin.val heq)
  nbr_adj := fun u v => by
    let t := tripleAt adjList u.val
    change tripleHas t v.val = true ↔ ∃ a : Fin 3, (⟨tripleNbr t a, hbound u a⟩ : Fin n) = v
    constructor
    · intro h
      simp only [tripleHas, Bool.or_eq_true, beq_iff_eq] at h
      rcases h with (h1 | h2) | h3
      · exact ⟨⟨0, by omega⟩, Fin.ext h1⟩
      · exact ⟨⟨1, by omega⟩, Fin.ext h2⟩
      · exact ⟨⟨2, by omega⟩, Fin.ext h3⟩
    · rintro ⟨a, ha⟩
      have hv : tripleNbr t a = v.val := congrArg Fin.val ha
      have ha3 : a.val = 0 ∨ a.val = 1 ∨ a.val = 2 := by omega
      rcases ha3 with h | h | h
      · have ha0 : a = ⟨0, by omega⟩ := Fin.ext h
        rw [ha0] at hv; simp [tripleHas, tripleNbr] at hv ⊢; left; left; exact hv
      · have ha1 : a = ⟨1, by omega⟩ := Fin.ext h
        rw [ha1] at hv; simp [tripleHas, tripleNbr] at hv ⊢; left; right; exact hv
      · have ha2 : a = ⟨2, by omega⟩ := Fin.ext h
        rw [ha2] at hv; simp [tripleHas, tripleNbr] at hv ⊢; right; exact hv

/-- Variant of `liftGraph_no_cycle` when `maxBaseLen = n` (covers ALL simple cycles of `B`,
    needing no `dMin` lower bound — ideal for graphs containing unexpanded `U_1` vertices!). -/
theorem liftGraph_no_cycle_all {n : Nat} (B : CubicBase n) (g : Fin n → Gadget3)
    (perm : Fin n → Fin 3 → Fin 3)
    (hperm : ∀ u : Fin n, ∀ a b : Fin 3, perm u a = perm u b → a = b)
    (T minReq : Nat) (hTreq : T < minReq)
    (hlocal : ∀ v : Fin n, ¬ (g v).graph.HasCycle T)
    (hcheck : B.graph.checkWeightedCycles (liftWeight B g perm) n minReq = true) :
    ¬ (liftGraph B g perm).HasCycle T := by
  rintro ⟨c⟩
  rcases liftGraph_cycle_dichotomy B g perm hperm c with ⟨v, hv, _⟩ | ⟨k, C, hlen⟩
  · exact hlocal v hv
  · have hk : k ≤ n := by
      by_cases hle : k ≤ n
      · exact hle
      · exfalso
        exact not_hasCycle_of_order_lt B.graph (by omega) ⟨C⟩
    have h1 := weighted_cycle_lower_of_check B.graph (liftWeight B g perm) n minReq hcheck C hk
    omega

/-- Helper: `liftGraph_no_cycle` using a single `minReq ≥ T + 1` check (avoids re-running DFS for smaller `T`). -/
theorem liftGraph_no_cycle_ge {n : Nat} (B : CubicBase n) (g : Fin n → Gadget3)
    (perm : Fin n → Fin 3 → Fin 3)
    (hperm : ∀ u : Fin n, ∀ a b : Fin 3, perm u a = perm u b → a = b)
    (T minReq maxBaseLen dMin : Nat)
    (hTreq : T < minReq)
    (hlocal : ∀ v : Fin n, ¬ (g v).graph.HasCycle T)
    (hdmin : ∀ (prev cur nxt : Fin n),
      B.graph.adj cur prev = true → B.graph.adj cur nxt = true → prev ≠ nxt →
      dMin ≤ liftWeight B g perm prev cur nxt)
    (hlong : T < (maxBaseLen + 1) * (1 + dMin))
    (hshort : B.graph.checkWeightedCycles (liftWeight B g perm) maxBaseLen minReq = true) :
    ¬ (liftGraph B g perm).HasCycle T := by
  rintro ⟨c⟩
  rcases liftGraph_cycle_dichotomy B g perm hperm c with ⟨v, hv, _⟩ | ⟨k, C, hlen⟩
  · exact hlocal v hv
  · by_cases hk : k ≤ maxBaseLen
    · have h1 := weighted_cycle_lower_of_check B.graph (liftWeight B g perm) maxBaseLen minReq hshort C hk
      omega
    · have hws : k * dMin ≤ cycleWeightSum C (liftWeight B g perm) := by
        have hL := C.hlen
        have hfold_lb : ∀ (xs : List (Fin k)),
            xs.length * dMin ≤
              xs.foldl (fun acc i => acc + liftWeight B g perm
                (C.vert ⟨(i.val + k - 1) % k, Nat.mod_lt _ (by omega)⟩)
                (C.vert i)
                (C.vert ⟨(i.val + 1) % k, Nat.mod_lt _ (by omega)⟩)) 0 := by
          intro xs
          induction xs with
          | nil => simp
          | cons i xs ih =>
            simp only [List.foldl_cons, Nat.zero_add, List.length_cons]
            rw [foldl_add_shift]
            have hprev_adj : B.graph.adj (C.vert i) (C.vert ⟨(i.val + k - 1) % k, Nat.mod_lt _ (by omega)⟩) = true := by
              rw [B.graph.symm]
              have he := C.edge ⟨(i.val + k - 1) % k, Nat.mod_lt _ (by omega)⟩
              have hm : ((i.val + k - 1) % k + 1) % k = i.val := by
                rw [Nat.mod_add_mod, show i.val + k - 1 + 1 = i.val + k by omega,
                    Nat.add_mod_right, Nat.mod_eq_of_lt i.isLt]
              simpa [hm] using he
            have hnxt_adj : B.graph.adj (C.vert i) (C.vert ⟨(i.val + 1) % k, Nat.mod_lt _ (by omega)⟩) = true :=
              C.edge i
            have hne : C.vert ⟨(i.val + k - 1) % k, Nat.mod_lt _ (by omega)⟩ ≠
                C.vert ⟨(i.val + 1) % k, Nat.mod_lt _ (by omega)⟩ := by
              intro heq
              have hfin := C.inj _ _ heq
              have hv : (i.val + k - 1) % k = (i.val + 1) % k := congrArg Fin.val hfin
              have hilt := i.isLt
              by_cases hi0 : i.val = 0
              · rw [hi0, Nat.zero_add, Nat.mod_eq_of_lt (by omega), Nat.mod_eq_of_lt (by omega)] at hv; omega
              · by_cases hi1 : i.val + 1 < k
                · rw [show i.val + k - 1 = i.val - 1 + k by omega, Nat.add_mod_right,
                      Nat.mod_eq_of_lt (by omega), Nat.mod_eq_of_lt hi1] at hv; omega
                · have hie : i.val = k - 1 := by omega
                  rw [hie, show k - 1 + k - 1 = (k - 2) + k by omega, Nat.add_mod_right,
                      Nat.mod_eq_of_lt (by omega), show k - 1 + 1 = k by omega, Nat.mod_self] at hv; omega
            have h1 := hdmin _ _ _ hprev_adj hnxt_adj hne
            have hmul : (xs.length + 1) * dMin = xs.length * dMin + dMin := by
              rw [Nat.add_mul, Nat.one_mul]
            omega
        simpa [cycleWeightSum] using hfold_lb (List.finRange k)
      have hkmul : (maxBaseLen + 1) * (1 + dMin) ≤ k * (1 + dMin) :=
        Nat.mul_le_mul_right (1 + dMin) (by omega)
      have hkd : k * (1 + dMin) = k + k * dMin := by rw [Nat.mul_add, Nat.mul_one]
      omega

/-- Cast a `FinGraph a` to `FinGraph b` along an order equality `a = b`. -/
def castGraph {a b : Nat} (h : a = b) (G : FinGraph a) : FinGraph b :=
  h ▸ G

theorem castGraph_minDeg {a b d : Nat} (h : a = b) (G : FinGraph a) (hG : G.MinDegAtLeast d) :
    (castGraph h G).MinDegAtLeast d := by subst h; exact hG

theorem castGraph_isCubic {a b : Nat} (h : a = b) (G : FinGraph a) (hG : G.IsCubic) :
    (castGraph h G).IsCubic := by subst h; exact hG

theorem castGraph_not_hasCycle {a b T : Nat} (h : a = b) (G : FinGraph a) (hG : ¬ G.HasCycle T) :
    ¬ (castGraph h G).HasCycle T := by subst h; exact hG

theorem gadget_not_hasCycle_of_eq {g1 g2 : Gadget3} (h : g1 = g2) {T : Nat}
    (h2 : ¬ g2.graph.HasCycle T) : ¬ g1.graph.HasCycle T := by
  subst h; exact h2

/-! ### 2. Base Graphs: Petersen (`n = 10`) and Tutte–Coxeter (`n = 30`) -/

def petersenTriples : List (Nat × Nat × Nat) :=
  [(1, 4, 5), (0, 2, 6), (1, 3, 7), (2, 4, 8), (0, 3, 9),
   (0, 7, 8), (1, 8, 9), (2, 5, 9), (3, 5, 6), (4, 6, 7)]

def petersenBase : CubicBase 10 :=
  cubicBaseOfTriples 10 petersenTriples
    (by decide) (by decide) (by decide) (by decide)

def tutteCoxeterTriples : List (Nat × Nat × Nat) :=
  [(1, 17, 29), (0, 2, 22), (1, 3, 9), (2, 4, 26), (3, 5, 13),
   (4, 6, 18), (5, 7, 23), (6, 8, 28), (7, 9, 15), (2, 8, 10),
   (9, 11, 19), (10, 12, 24), (11, 13, 29), (4, 12, 14), (13, 15, 21),
   (8, 14, 16), (15, 17, 25), (0, 16, 18), (5, 17, 19), (10, 18, 20),
   (19, 21, 27), (14, 20, 22), (1, 21, 23), (6, 22, 24), (11, 23, 25),
   (16, 24, 26), (3, 25, 27), (20, 26, 28), (7, 27, 29), (0, 12, 28)]

def tutteCoxeterBase : CubicBase 30 :=
  cubicBaseOfTriples 30 tutteCoxeterTriples
    (by decide) (by decide) (by decide) (by decide)

theorem H7_dl_ge2 : ∀ a b : Fin 3, a ≠ b → 2 ≤ H7.distLower a b := by decide
theorem H8star_dl_ge2 : ∀ a b : Fin 3, a ≠ b → 2 ≤ H8star.distLower a b := by decide
theorem H15_dl_ge3 : ∀ a b : Fin 3, a ≠ b → 3 ≤ H15.distLower a b := by decide

/-! ### 3. Record 1: `f_{δ≥3}(4) ≤ 73` (`Petersen + 3·H_8* + 7·H_7`) -/

def pet73v1Gadget (v : Fin 10) : Gadget3 :=
  if v.val < 3 then H8star else H7

def pet73v1Choice : List Nat := [0, 2, 0, 0, 0, 0, 0, 0, 2, 1]

def pet73v1Perm (v : Fin 10) : Fin 3 → Fin 3 :=
  rotPerm ⟨(pet73v1Choice.getD v.val 0) % 3, Nat.mod_lt _ (by omega)⟩

theorem pet73v1_order : liftOrder pet73v1Gadget = 73 := by decide

theorem pet73v1_check :
    petersenBase.graph.checkWeightedCycles
      (liftWeight petersenBase pet73v1Gadget pet73v1Perm) 10 17 = true := by
  decide

/-- **Theorem (`f_delta3_4_le_73`)**:
    There exists a 73-vertex simple graph with minimum degree `≥ 3` and no `C4`, `C8`, or `C16`
    (built as `Petersen + 3·H_8* + 7·H_7`). -/
theorem f_delta3_4_le_73 :
    ∃ G : FinGraph 73,
      G.MinDegAtLeast 3 ∧ ¬ G.HasCycle 4 ∧ ¬ G.HasCycle 8 ∧ ¬ G.HasCycle 16 := by
  let G0 := liftGraph petersenBase pet73v1Gadget pet73v1Perm
  have hperm : ∀ u : Fin 10, ∀ a b : Fin 3, pet73v1Perm u a = pet73v1Perm u b → a = b :=
    fun u => rotPerm_inj _
  have hdeg : G0.MinDegAtLeast 3 := liftGraph_minDeg3 petersenBase pet73v1Gadget pet73v1Perm hperm
  have hno : ∀ T : Nat, T = 4 ∨ T = 8 ∨ T = 16 → ¬ G0.HasCycle T := by
    intro T hT
    apply liftGraph_no_cycle_all petersenBase pet73v1Gadget pet73v1Perm hperm T 17
      (by rcases hT with rfl | rfl | rfl <;> omega)
    · intro v
      by_cases hv : v.val < 3
      · apply gadget_not_hasCycle_of_eq (show pet73v1Gadget v = H8star by simp [pet73v1Gadget, hv])
        rcases hT with rfl | rfl | rfl
        · exact H8star_no_C4
        · exact H8star_no_C8
        · exact not_hasCycle_of_order_lt H8star.graph (by decide)
      · apply gadget_not_hasCycle_of_eq (show pet73v1Gadget v = H7 by simp [pet73v1Gadget, hv])
        rcases hT with rfl | rfl | rfl
        · exact H7_no_C4
        · exact H7_no_C8
        · exact not_hasCycle_of_order_lt H7.graph (by decide)
    · exact pet73v1_check
  exact ⟨castGraph pet73v1_order G0,
    castGraph_minDeg pet73v1_order G0 hdeg,
    castGraph_not_hasCycle pet73v1_order G0 (hno 4 (Or.inl rfl)),
    castGraph_not_hasCycle pet73v1_order G0 (hno 8 (Or.inr (Or.inl rfl))),
    castGraph_not_hasCycle pet73v1_order G0 (hno 16 (Or.inr (Or.inr rfl)))⟩

/-! ### 4. Record 1 (Alternative Witness): `f_{δ≥3}(4) ≤ 73` (`Petersen + 1·U_1 + 9·H_8*`) -/

def pet73v2Gadget (v : Fin 10) : Gadget3 :=
  if v.val == 0 then unitGadget else H8star

def pet73v2Choice : List Nat := [0, 0, 0, 1, 0, 0, 0, 1, 1, 0]

def pet73v2Perm (v : Fin 10) : Fin 3 → Fin 3 :=
  rotPerm ⟨(pet73v2Choice.getD v.val 0) % 3, Nat.mod_lt _ (by omega)⟩

theorem pet73v2_order : liftOrder pet73v2Gadget = 73 := by decide

theorem pet73v2_check :
    petersenBase.graph.checkWeightedCycles
      (liftWeight petersenBase pet73v2Gadget pet73v2Perm) 10 17 = true := by
  decide

/-- **Theorem (`f_delta3_4_le_73_alt`)**:
    Second structurally distinct 73-vertex witness (`Petersen + 1·U_1 + 9·H_8*`,
    64 deg-3 vertices and 9 deg-4 vertices) with minimum degree `≥ 3` and no `C4`, `C8`, or `C16`. -/
theorem f_delta3_4_le_73_alt :
    ∃ G : FinGraph 73,
      G.MinDegAtLeast 3 ∧ ¬ G.HasCycle 4 ∧ ¬ G.HasCycle 8 ∧ ¬ G.HasCycle 16 := by
  let G0 := liftGraph petersenBase pet73v2Gadget pet73v2Perm
  have hperm : ∀ u : Fin 10, ∀ a b : Fin 3, pet73v2Perm u a = pet73v2Perm u b → a = b :=
    fun u => rotPerm_inj _
  have hdeg : G0.MinDegAtLeast 3 := liftGraph_minDeg3 petersenBase pet73v2Gadget pet73v2Perm hperm
  have hno : ∀ T : Nat, T = 4 ∨ T = 8 ∨ T = 16 → ¬ G0.HasCycle T := by
    intro T hT
    apply liftGraph_no_cycle_all petersenBase pet73v2Gadget pet73v2Perm hperm T 17
      (by rcases hT with rfl | rfl | rfl <;> omega)
    · intro v
      by_cases hv : (v.val == 0) = true
      · apply gadget_not_hasCycle_of_eq (show pet73v2Gadget v = unitGadget by simp [pet73v2Gadget, hv])
        rcases hT with rfl | rfl | rfl <;>
          exact not_hasCycle_of_order_lt unitGadget.graph (by decide)
      · apply gadget_not_hasCycle_of_eq (show pet73v2Gadget v = H8star by simp [pet73v2Gadget, hv])
        rcases hT with rfl | rfl | rfl
        · exact H8star_no_C4
        · exact H8star_no_C8
        · exact not_hasCycle_of_order_lt H8star.graph (by decide)
    · exact pet73v2_check
  exact ⟨castGraph pet73v2_order G0,
    castGraph_minDeg pet73v2_order G0 hdeg,
    castGraph_not_hasCycle pet73v2_order G0 (hno 4 (Or.inl rfl)),
    castGraph_not_hasCycle pet73v2_order G0 (hno 8 (Or.inr (Or.inl rfl))),
    castGraph_not_hasCycle pet73v2_order G0 (hno 16 (Or.inr (Or.inr rfl)))⟩

/-! ### 5. Record 2: `f_cubic(5) ≤ 370` (`Tutte–Coxeter + 20·H_15 + 10·H_7`) -/

def tc370Type : List Nat :=
  [2,1,2,2,1,1,2,2,2,2,1,1,2,2,2,1,1,2,2,2,2,2,1,2,2,2,2,1,1,2]

def tc370Choice : List Nat :=
  [2,0,1,2,2,1,1,1,1,0,2,2,1,2,2,1,2,0,1,1,0,1,2,0,1,1,1,0,0,1]

def tc370Gadget (v : Fin 30) : Gadget3 :=
  if tc370Type.getD v.val 2 == 2 then H15 else H7

def tc370Perm (v : Fin 30) : Fin 3 → Fin 3 :=
  rotPerm ⟨(tc370Choice.getD v.val 0) % 3, Nat.mod_lt _ (by omega)⟩

theorem tc370_order : liftOrder tc370Gadget = 370 := by decide

theorem tc370_check33 :
    tutteCoxeterBase.graph.checkWeightedCycles
      (liftWeight tutteCoxeterBase tc370Gadget tc370Perm) 10 33 = true := by
  decide

/-- **Theorem (`f_cubic_5_le_370`)**:
    There exists a 370-vertex cubic (`3`-regular) simple graph with no `C4`, `C8`, `C16`, or `C32`
    (built as `Tutte–Coxeter + 20·H_15 + 10·H_7`). -/
theorem f_cubic_5_le_370 :
    ∃ G : FinGraph 370,
      G.IsCubic ∧ ¬ G.HasCycle 4 ∧ ¬ G.HasCycle 8 ∧ ¬ G.HasCycle 16 ∧ ¬ G.HasCycle 32 := by
  let G0 := liftGraph tutteCoxeterBase tc370Gadget tc370Perm
  have hperm : ∀ u : Fin 30, ∀ a b : Fin 3, tc370Perm u a = tc370Perm u b → a = b :=
    fun u => rotPerm_inj _
  have hcub : G0.IsCubic := by
    apply liftGraph_isCubic tutteCoxeterBase tc370Gadget tc370Perm hperm
    intro u
    by_cases hu : (tc370Type.getD u.val 2 == 2) = true
    · simp only [tc370Gadget, hu, ↓reduceIte]; exact H15_isCubicInternal
    · simp only [tc370Gadget, hu]; exact H7_isCubicInternal
  have hdmin : ∀ (prev cur nxt : Fin 30),
      tutteCoxeterBase.graph.adj cur prev = true →
      tutteCoxeterBase.graph.adj cur nxt = true →
      prev ≠ nxt →
      2 ≤ liftWeight tutteCoxeterBase tc370Gadget tc370Perm prev cur nxt := by
    intro prev cur nxt hp hn hne
    have hep := tutteCoxeterBase.edgePort_ne_of_ne hp hn hne
    have hpne : tc370Perm cur (tutteCoxeterBase.edgePort cur prev) ≠
        tc370Perm cur (tutteCoxeterBase.edgePort cur nxt) :=
      fun h => hep (hperm cur _ _ h)
    by_cases hu : (tc370Type.getD cur.val 2 == 2) = true
    · simp only [liftWeight, tc370Gadget, hu, ↓reduceIte]
      exact Nat.le_trans (by omega) (H15_dl_ge3 _ _ hpne)
    · simp only [liftWeight, tc370Gadget, hu]
      exact H7_dl_ge2 _ _ hpne
  have hno : ∀ T : Nat, T = 4 ∨ T = 8 ∨ T = 16 ∨ T = 32 → ¬ G0.HasCycle T := by
    intro T hT
    apply liftGraph_no_cycle_ge tutteCoxeterBase tc370Gadget tc370Perm hperm T 33 10 2
      (by rcases hT with rfl | rfl | rfl | rfl <;> omega)
      (by
        intro v
        by_cases hv : (tc370Type.getD v.val 2 == 2) = true
        · apply gadget_not_hasCycle_of_eq (show tc370Gadget v = H15 by simp only [tc370Gadget, hv, ↓reduceIte])
          rcases hT with rfl | rfl | rfl | rfl
          · exact H15_no_C4
          · exact H15_no_C8
          · exact not_hasCycle_of_order_lt H15.graph (by decide)
          · exact not_hasCycle_of_order_lt H15.graph (by decide)
        · apply gadget_not_hasCycle_of_eq (show tc370Gadget v = H7 by simp only [tc370Gadget, hv]; rfl)
          rcases hT with rfl | rfl | rfl | rfl
          · exact H7_no_C4
          · exact H7_no_C8
          · exact not_hasCycle_of_order_lt H7.graph (by decide)
          · exact not_hasCycle_of_order_lt H7.graph (by decide))
      hdmin
      (by rcases hT with rfl | rfl | rfl | rfl <;> omega)
      tc370_check33
  exact ⟨castGraph tc370_order G0,
    castGraph_isCubic tc370_order G0 hcub,
    castGraph_not_hasCycle tc370_order G0 (hno 4 (Or.inl rfl)),
    castGraph_not_hasCycle tc370_order G0 (hno 8 (Or.inr (Or.inl rfl))),
    castGraph_not_hasCycle tc370_order G0 (hno 16 (Or.inr (Or.inr (Or.inl rfl)))),
    castGraph_not_hasCycle tc370_order G0 (hno 32 (Or.inr (Or.inr (Or.inr rfl))))⟩

/-! ### 6. Record 3: `f_{δ≥3}(5) ≤ 345` (`Tutte–Coxeter + 15·H_15 + 15·H_8*`) -/

def tc345Type : List Nat :=
  [2,2,2,3,3,2,3,2,2,3,3,3,3,3,2,2,2,3,2,3,3,2,2,3,3,2,3,3,2,2]

def tc345Choice : List Nat :=
  [2,0,0,2,0,2,2,1,2,2,1,1,1,0,2,1,0,2,1,0,0,2,0,2,0,0,2,0,0,2]

def tc345Gadget (v : Fin 30) : Gadget3 :=
  if tc345Type.getD v.val 2 == 2 then H15 else H8star

def tc345Perm (v : Fin 30) : Fin 3 → Fin 3 :=
  rotPerm ⟨(tc345Choice.getD v.val 0) % 3, Nat.mod_lt _ (by omega)⟩

theorem tc345_order : liftOrder tc345Gadget = 345 := by decide

theorem tc345_check33 :
    tutteCoxeterBase.graph.checkWeightedCycles
      (liftWeight tutteCoxeterBase tc345Gadget tc345Perm) 10 33 = true := by
  decide

/-- **Theorem (`f_delta3_5_le_345`)**:
    There exists a 345-vertex simple graph with minimum degree `≥ 3` and no `C4`, `C8`, `C16`, or `C32`
    (built as `Tutte–Coxeter + 15·H_15 + 15·H_8*`). -/
theorem f_delta3_5_le_345 :
    ∃ G : FinGraph 345,
      G.MinDegAtLeast 3 ∧ ¬ G.HasCycle 4 ∧ ¬ G.HasCycle 8 ∧ ¬ G.HasCycle 16 ∧ ¬ G.HasCycle 32 := by
  let G0 := liftGraph tutteCoxeterBase tc345Gadget tc345Perm
  have hperm : ∀ u : Fin 30, ∀ a b : Fin 3, tc345Perm u a = tc345Perm u b → a = b :=
    fun u => rotPerm_inj _
  have hdeg : G0.MinDegAtLeast 3 :=
    liftGraph_minDeg3 tutteCoxeterBase tc345Gadget tc345Perm hperm
  have hdmin : ∀ (prev cur nxt : Fin 30),
      tutteCoxeterBase.graph.adj cur prev = true →
      tutteCoxeterBase.graph.adj cur nxt = true →
      prev ≠ nxt →
      2 ≤ liftWeight tutteCoxeterBase tc345Gadget tc345Perm prev cur nxt := by
    intro prev cur nxt hp hn hne
    have hep := tutteCoxeterBase.edgePort_ne_of_ne hp hn hne
    have hpne : tc345Perm cur (tutteCoxeterBase.edgePort cur prev) ≠
        tc345Perm cur (tutteCoxeterBase.edgePort cur nxt) :=
      fun h => hep (hperm cur _ _ h)
    by_cases hu : (tc345Type.getD cur.val 2 == 2) = true
    · simp only [liftWeight, tc345Gadget, hu, ↓reduceIte]
      exact Nat.le_trans (by omega) (H15_dl_ge3 _ _ hpne)
    · simp only [liftWeight, tc345Gadget, hu]
      exact H8star_dl_ge2 _ _ hpne
  have hno : ∀ T : Nat, T = 4 ∨ T = 8 ∨ T = 16 ∨ T = 32 → ¬ G0.HasCycle T := by
    intro T hT
    apply liftGraph_no_cycle_ge tutteCoxeterBase tc345Gadget tc345Perm hperm T 33 10 2
      (by rcases hT with rfl | rfl | rfl | rfl <;> omega)
      (by
        intro v
        by_cases hv : (tc345Type.getD v.val 2 == 2) = true
        · apply gadget_not_hasCycle_of_eq (show tc345Gadget v = H15 by simp only [tc345Gadget, hv, ↓reduceIte])
          rcases hT with rfl | rfl | rfl | rfl
          · exact H15_no_C4
          · exact H15_no_C8
          · exact not_hasCycle_of_order_lt H15.graph (by decide)
          · exact not_hasCycle_of_order_lt H15.graph (by decide)
        · apply gadget_not_hasCycle_of_eq (show tc345Gadget v = H8star by simp only [tc345Gadget, hv]; rfl)
          rcases hT with rfl | rfl | rfl | rfl
          · exact H8star_no_C4
          · exact H8star_no_C8
          · exact not_hasCycle_of_order_lt H8star.graph (by decide)
          · exact not_hasCycle_of_order_lt H8star.graph (by decide))
      hdmin
      (by rcases hT with rfl | rfl | rfl | rfl <;> omega)
      tc345_check33
  exact ⟨castGraph tc345_order G0,
    castGraph_minDeg tc345_order G0 hdeg,
    castGraph_not_hasCycle tc345_order G0 (hno 4 (Or.inl rfl)),
    castGraph_not_hasCycle tc345_order G0 (hno 8 (Or.inr (Or.inl rfl))),
    castGraph_not_hasCycle tc345_order G0 (hno 16 (Or.inr (Or.inr (Or.inl rfl)))),
    castGraph_not_hasCycle tc345_order G0 (hno 32 (Or.inr (Or.inr (Or.inr rfl))))⟩

/-! ### 7. General Record 4: `f_cubic(6)` via Greedy 4-Packing on ANY Cubic Girth-`≥ 17` Base -/

private theorem nodup_len_le {α : Type} [DecidableEq α] :
    ∀ (xs ys : List α), xs.Nodup → (∀ a, a ∈ xs → a ∈ ys) → xs.length ≤ ys.length
  | [], _, _, _ => Nat.zero_le _
  | x :: xs, ys, hnd, hsub => by
    rw [List.nodup_cons] at hnd
    have hx : x ∈ ys := hsub x (List.mem_cons_self ..)
    have hsub' : ∀ a, a ∈ xs → a ∈ ys.erase x := by
      intro a ha
      have hne : a ≠ x := fun h => hnd.1 (h ▸ ha)
      exact (List.mem_erase_of_ne hne).mpr (hsub a (List.mem_cons_of_mem x ha))
    have hih := nodup_len_le xs (ys.erase x) hnd.2 hsub'
    have hlen : (ys.erase x).length + 1 = ys.length := by
      rw [List.length_erase_of_mem hx]
      have hpos : 0 < ys.length := List.length_pos_of_mem hx
      omega
    simp only [List.length_cons]
    omega

private theorem len_filter_eq {m : Nat} (p : Fin m → Bool) (ws : List (Fin m))
    (hnd : ws.Nodup) (hiff : ∀ z : Fin m, z ∈ ws ↔ p z = true) :
    ((List.finRange m).filter p).length = ws.length := by
  have h1 : ((List.finRange m).filter p).length ≤ ws.length :=
    nodup_len_le _ _ ((List.nodup_finRange m).filter p) fun z hz =>
      (hiff z).mpr (List.mem_filter.mp hz).2
  have h2 : ws.length ≤ ((List.finRange m).filter p).length :=
    nodup_len_le _ _ hnd fun z hz =>
      List.mem_filter.mpr ⟨List.mem_finRange z, (hiff z).mp hz⟩
  omega

/-- Non-backtracking neighbors of `x` avoiding `parent` in a cubic base `B`.
    When `B.graph.adj x parent = true`, this list has length at most `2`. -/
def stepNbrs {N : Nat} (B : CubicBase N) (parent x : Fin N) : List (Fin N) :=
  ((List.finRange 3).filter (fun k => B.nbr x k != parent)).map (B.nbr x)

theorem stepNbrs_length_le2 {N : Nat} (B : CubicBase N) (parent x : Fin N)
    (hadj : B.graph.adj x parent = true) :
    (stepNbrs B parent x).length ≤ 2 := by
  obtain ⟨k0, hk0⟩ := (B.nbr_adj x parent).mp hadj
  have hsub : ∀ a, a ∈ (List.finRange 3).filter (fun k => B.nbr x k != parent) →
      a ∈ (List.finRange 3).filter (fun k => k != k0) := by
    intro a ha
    simp only [List.mem_filter, List.mem_finRange, true_and, bne_iff_ne] at ha ⊢
    intro heq; subst heq; exact ha hk0
  have hlen_k0 : ((List.finRange 3).filter (fun k => k != k0)).length = 2 := by
    have hall : ∀ k : Fin 3, ((List.finRange 3).filter (fun a => a != k)).length = 2 := by decide
    exact hall k0
  have hle := nodup_len_le _ _ ((List.nodup_finRange 3).filter _) hsub
  simp only [stepNbrs, List.length_map]
  omega

/-- The non-backtracking closed ball of radius `4` around `u` in a cubic base `B`:
    at most `1 + 3 + 6 + 12 + 24 = 46` vertices! -/
def ball4Pairs {N : Nat} (B : CubicBase N) (u : Fin N) : List (Fin N) :=
  let s1 : List (Fin N × Fin N) := (List.finRange 3).map (fun k => (u, B.nbr u k))
  let s2 : List (Fin N × Fin N) := s1.flatMap (fun p => (stepNbrs B p.1 p.2).map (fun y => (p.2, y)))
  let s3 : List (Fin N × Fin N) := s2.flatMap (fun p => (stepNbrs B p.1 p.2).map (fun y => (p.2, y)))
  let s4 : List (Fin N × Fin N) := s3.flatMap (fun p => (stepNbrs B p.1 p.2).map (fun y => (p.2, y)))
  [u] ++ s1.map Prod.snd ++ s2.map Prod.snd ++ s3.map Prod.snd ++ s4.map Prod.snd

private theorem flatMap_length_le {α β : Type} (xs : List α) (f : α → List β) (c : Nat)
    (hc : ∀ x, x ∈ xs → (f x).length ≤ c) :
    (xs.flatMap f).length ≤ xs.length * c := by
  induction xs with
  | nil => simp
  | cons x xs ih =>
    simp only [List.flatMap_cons, List.length_append, List.length_cons]
    have h1 := hc x (List.mem_cons_self ..)
    have h2 := ih (fun y hy => hc y (List.mem_cons_of_mem x hy))
    rw [Nat.add_mul, Nat.one_mul]
    omega

theorem ball4_length_le46 {N : Nat} (B : CubicBase N) (u : Fin N) :
    (ball4Pairs B u).length ≤ 46 := by
  let s1 : List (Fin N × Fin N) := (List.finRange 3).map (fun k => (u, B.nbr u k))
  let step (p : Fin N × Fin N) : List (Fin N × Fin N) :=
    (stepNbrs B p.1 p.2).map (fun y => (p.2, y))
  have hadj_s1 : ∀ p, p ∈ s1 → B.graph.adj p.2 p.1 = true := by
    intro p hp
    simp only [s1, List.mem_map, List.mem_finRange, true_and] at hp
    obtain ⟨k, rfl⟩ := hp
    rw [B.graph.symm]
    exact (B.nbr_adj u _).mpr ⟨k, rfl⟩
  have hadj_step : ∀ p q, q ∈ step p → B.graph.adj q.2 q.1 = true := by
    intro p q hq
    simp only [step, stepNbrs, List.mem_map, List.mem_filter, List.mem_finRange, true_and] at hq
    obtain ⟨y, ⟨k, _, rfl⟩, rfl⟩ := hq
    rw [B.graph.symm]
    exact (B.nbr_adj p.2 _).mpr ⟨k, rfl⟩
  have hlen_step : ∀ p, B.graph.adj p.2 p.1 = true → (step p).length ≤ 2 := by
    intro p hp
    simp only [step, List.length_map]
    exact stepNbrs_length_le2 B p.1 p.2 hp
  let s2 := s1.flatMap step
  let s3 := s2.flatMap step
  let s4 := s3.flatMap step
  have hs1_len : s1.length = 3 := by simp [s1]
  have hs2_len : s2.length ≤ 6 := by
    have h : s2.length ≤ s1.length * 2 :=
      flatMap_length_le s1 step 2 (fun p hp => hlen_step p (hadj_s1 p hp))
    omega
  have hadj_s2 : ∀ p, p ∈ s2 → B.graph.adj p.2 p.1 = true := by
    intro p hp
    simp only [s2, List.mem_flatMap] at hp
    obtain ⟨q, _, hqp⟩ := hp
    exact hadj_step q p hqp
  have hs3_len : s3.length ≤ 12 := by
    have h : s3.length ≤ s2.length * 2 :=
      flatMap_length_le s2 step 2 (fun p hp => hlen_step p (hadj_s2 p hp))
    omega
  have hadj_s3 : ∀ p, p ∈ s3 → B.graph.adj p.2 p.1 = true := by
    intro p hp
    simp only [s3, List.mem_flatMap] at hp
    obtain ⟨q, _, hqp⟩ := hp
    exact hadj_step q p hqp
  have hs4_len : s4.length ≤ 24 := by
    have h : s4.length ≤ s3.length * 2 :=
      flatMap_length_le s3 step 2 (fun p hp => hlen_step p (hadj_s3 p hp))
    omega
  change ([u] ++ s1.map Prod.snd ++ s2.map Prod.snd ++ s3.map Prod.snd ++ s4.map Prod.snd).length ≤ 46
  simp only [List.length_append, List.length_cons, List.length_nil, List.length_map]
  omega

/-- Any `SimplePath` of length `d ≤ 4` from `u` to `v` in `B` witnesses `v ∈ ball4Pairs B u`! -/
theorem mem_ball4_of_simplePath {N : Nat} (B : CubicBase N) {u v : Fin N} {d : Nat}
    (hd : d ≤ 4) (p : SimplePath B.graph u v d) :
    v ∈ ball4Pairs B u := by
  let s1 : List (Fin N × Fin N) := (List.finRange 3).map (fun k => (u, B.nbr u k))
  let step (q : Fin N × Fin N) : List (Fin N × Fin N) :=
    (stepNbrs B q.1 q.2).map (fun y => (q.2, y))
  let s2 := s1.flatMap step
  let s3 := s2.flatMap step
  let s4 := s3.flatMap step
  have hstep_mem : ∀ (a b c : Fin N), B.graph.adj b c = true → c ≠ a → (b, c) ∈ step (a, b) := by
    intro a b c hadj hne
    obtain ⟨k, hk⟩ := (B.nbr_adj b c).mp hadj
    simp only [step, stepNbrs, List.mem_map, List.mem_filter, List.mem_finRange, true_and, bne_iff_ne]
    exact ⟨c, ⟨k, by rw [hk]; exact hne, hk⟩, rfl⟩
  have hm1 : ∀ (h1 : 1 ≤ d), (p.vert ⟨0, by omega⟩, p.vert ⟨1, by omega⟩) ∈ s1 := by
    intro h1
    have he := p.edge ⟨0, by omega⟩
    rw [p.start_eq] at he
    obtain ⟨k, hk⟩ := (B.nbr_adj u _).mp he
    simp only [s1, List.mem_map, List.mem_finRange, true_and]
    exact ⟨k, by rw [p.start_eq, hk]⟩
  have hm_next : ∀ (t : Nat) (ht : t + 2 ≤ d),
      (p.vert ⟨t + 1, by omega⟩, p.vert ⟨t + 2, by omega⟩) ∈
        step (p.vert ⟨t, by omega⟩, p.vert ⟨t + 1, by omega⟩) := by
    intro t ht
    apply hstep_mem
    · exact p.edge ⟨t + 1, by omega⟩
    · intro heq
      have := p.inj ⟨t + 2, by omega⟩ ⟨t, by omega⟩ heq
      have hv := congrArg Fin.val this
      simp at hv
  change v ∈ [u] ++ s1.map Prod.snd ++ s2.map Prod.snd ++ s3.map Prod.snd ++ s4.map Prod.snd
  have hmatch : d = 0 ∨ d = 1 ∨ d = 2 ∨ d = 3 ∨ d = 4 := by omega
  rcases hmatch with rfl | rfl | rfl | rfl | rfl
  · have : u = v := p.start_eq.symm.trans p.end_eq
    subst this; simp
  · have h := hm1 (by omega)
    rw [p.end_eq] at h
    simp only [List.mem_append, List.mem_map]
    left; left; left; right
    exact ⟨(p.vert ⟨0, by omega⟩, v), h, rfl⟩
  · have h1 := hm1 (by omega)
    have h2 := hm_next 0 (by omega)
    have hm2 : (p.vert ⟨1, by omega⟩, p.vert ⟨2, by omega⟩) ∈ s2 :=
      List.mem_flatMap.mpr ⟨_, h1, h2⟩
    rw [p.end_eq] at hm2
    simp only [List.mem_append, List.mem_map]
    left; left; right
    exact ⟨(p.vert ⟨1, by omega⟩, v), hm2, rfl⟩
  · have h1 := hm1 (by omega)
    have h2 : (p.vert ⟨1, by omega⟩, p.vert ⟨2, by omega⟩) ∈ s2 :=
      List.mem_flatMap.mpr ⟨_, h1, hm_next 0 (by omega)⟩
    have hm3 : (p.vert ⟨2, by omega⟩, p.vert ⟨3, by omega⟩) ∈ s3 :=
      List.mem_flatMap.mpr ⟨_, h2, hm_next 1 (by omega)⟩
    rw [p.end_eq] at hm3
    simp only [List.mem_append, List.mem_map]
    left; right
    exact ⟨(p.vert ⟨2, by omega⟩, v), hm3, rfl⟩
  · have h1 := hm1 (by omega)
    have h2 : (p.vert ⟨1, by omega⟩, p.vert ⟨2, by omega⟩) ∈ s2 :=
      List.mem_flatMap.mpr ⟨_, h1, hm_next 0 (by omega)⟩
    have h3 : (p.vert ⟨2, by omega⟩, p.vert ⟨3, by omega⟩) ∈ s3 :=
      List.mem_flatMap.mpr ⟨_, h2, hm_next 1 (by omega)⟩
    have hm4 : (p.vert ⟨3, by omega⟩, p.vert ⟨4, by omega⟩) ∈ s4 :=
      List.mem_flatMap.mpr ⟨_, h3, hm_next 2 (by omega)⟩
    rw [p.end_eq] at hm4
    simp only [List.mem_append, List.mem_map]
    right
    exact ⟨(p.vert ⟨3, by omega⟩, v), hm4, rfl⟩

/-- Reverse a `SimplePath` from `u` to `v` into one from `v` to `u`. -/
def reversePath {N : Nat} {G : FinGraph N} {u v : Fin N} {d : Nat} (p : SimplePath G u v d) :
    SimplePath G v u d where
  vert i := p.vert ⟨d - i.val, by omega⟩
  start_eq := by simpa using p.end_eq
  end_eq := by simpa using p.start_eq
  inj i j hij := by
    have h := congrArg Fin.val (p.inj _ _ hij)
    simp at h
    exact Fin.ext (by omega)
  edge i := by
    have he := p.edge ⟨d - 1 - i.val, by omega⟩
    rw [G.symm] at he
    have hf1 : (⟨d - 1 - i.val + 1, by omega⟩ : Fin (d + 1)) = ⟨d - i.val, by omega⟩ :=
      Fin.ext (by change d - 1 - i.val + 1 = d - i.val; omega)
    have hf2 : (⟨d - 1 - i.val, by omega⟩ : Fin (d + 1)) = ⟨d - (i.val + 1), by omega⟩ :=
      Fin.ext (by change d - 1 - i.val = d - (i.val + 1); omega)
    rw [hf1, hf2] at he
    exact he

/-- Greedy maximal 4-packing of `B`: scan `xs`, adding `u` whenever `u` is not in any `ball4` of `acc`. -/
def greedy4PackAux {N : Nat} (B : CubicBase N) : List (Fin N) → List (Fin N) → List (Fin N)
  | [], acc => acc
  | u :: rest, acc =>
    if acc.any (fun w => (ball4Pairs B w).contains u) then
      greedy4PackAux B rest acc
    else
      greedy4PackAux B rest (u :: acc)

def greedy4Pack {N : Nat} (B : CubicBase N) : List (Fin N) :=
  greedy4PackAux B (List.finRange N) []

/-- Properties of `greedy4PackAux`: nodup, 4-packing separation (no `SimplePath` of length `≤ 4`
    between distinct elements), and domination (every scanned vertex lies in some `ball4`). -/
theorem greedy4PackAux_props {N : Nat} (B : CubicBase N) :
    ∀ (xs acc : List (Fin N)),
      acc.Nodup →
      (∀ a b, a ∈ acc → b ∈ acc → a ≠ b → ∀ d ≤ 4, ¬ Nonempty (SimplePath B.graph a b d)) →
      let res := greedy4PackAux B xs acc
      res.Nodup ∧
      (∀ w, w ∈ acc → w ∈ res) ∧
      (∀ u, u ∈ xs → ∃ w, w ∈ res ∧ u ∈ ball4Pairs B w) ∧
      (∀ a b, a ∈ res → b ∈ res → a ≠ b → ∀ d ≤ 4, ¬ Nonempty (SimplePath B.graph a b d))
  | [], acc, hnd, hsep => by
    refine ⟨hnd, fun _ hw => hw, fun _ hu => by simp at hu, hsep⟩
  | u :: rest, acc, hnd, hsep => by
    simp only [greedy4PackAux]
    split
    · rename_i hcov
      obtain ⟨hnd', hsub', hdom', hsep'⟩ := greedy4PackAux_props B rest acc hnd hsep
      refine ⟨hnd', hsub', ?_, hsep'⟩
      intro x hx
      rcases List.mem_cons.mp hx with rfl | hx'
      · simp only [List.any_eq_true, List.contains_iff_mem] at hcov
        obtain ⟨w, hw, hball⟩ := hcov
        exact ⟨w, hsub' w hw, hball⟩
      · exact hdom' x hx'
    · rename_i huncov
      have hnot_in_ball : ∀ w, w ∈ acc → u ∉ ball4Pairs B w := by
        intro w hw hm
        apply huncov
        simp only [List.any_eq_true, List.contains_iff_mem]
        exact ⟨w, hw, hm⟩
      have hu_not_acc : u ∉ acc := by
        intro hm
        have hself : u ∈ ball4Pairs B u := by simp [ball4Pairs]
        exact hnot_in_ball u hm hself
      have hnd1 : (u :: acc).Nodup := List.nodup_cons.mpr ⟨hu_not_acc, hnd⟩
      have hsep1 : ∀ a b, a ∈ u :: acc → b ∈ u :: acc → a ≠ b →
          ∀ d ≤ 4, ¬ Nonempty (SimplePath B.graph a b d) := by
        intro a b ha hb hne d hd ⟨p⟩
        rcases List.mem_cons.mp ha with rfl | ha' <;> rcases List.mem_cons.mp hb with rfl | hb'
        · exact hne rfl
        · exact hnot_in_ball b hb' (mem_ball4_of_simplePath B hd (reversePath p))
        · exact hnot_in_ball a ha' (mem_ball4_of_simplePath B hd p)
        · exact hsep a b ha' hb' hne d hd ⟨p⟩
      obtain ⟨hnd', hsub', hdom', hsep'⟩ := greedy4PackAux_props B rest (u :: acc) hnd1 hsep1
      refine ⟨hnd', fun w hw => hsub' w (List.mem_cons_of_mem u hw), ?_, hsep'⟩
      intro x hx
      rcases List.mem_cons.mp hx with rfl | hx'
      · exact ⟨x, hsub' x (List.mem_cons_self ..), by simp [ball4Pairs]⟩
      · exact hdom' x hx'

/-- Size bound: a greedy maximal 4-packing of any cubic graph on `N` vertices satisfies `N ≤ 46 * |P|`. -/
theorem greedy4Pack_size_bound {N : Nat} (B : CubicBase N) :
    N ≤ 46 * (greedy4Pack B).length := by
  obtain ⟨_, _, hdom, _⟩ := greedy4PackAux_props B (List.finRange N) [] List.nodup_nil
    (fun _ _ ha => by simp at ha)
  let P := greedy4Pack B
  have hsub : ∀ u, u ∈ List.finRange N → u ∈ P.flatMap (ball4Pairs B) := by
    intro u hu
    obtain ⟨w, hw, hball⟩ := hdom u hu
    exact List.mem_flatMap.mpr ⟨w, hw, hball⟩
  have hle1 := nodup_len_le _ _ (List.nodup_finRange N) hsub
  have hle2 := flatMap_length_le P (ball4Pairs B) 46 (fun w _ => ball4_length_le46 B w)
  simp only [List.length_finRange] at hle1
  rw [Nat.mul_comm] at hle2
  exact Nat.le_trans hle1 hle2

/-- Total order of lifting `P ↦ H_7` and `V \ P ↦ H_15` is `15 * N - 8 * |P|`. -/
theorem liftOrder_H7_H15 {N : Nat} (P : List (Fin N)) (hnd : P.Nodup) :
    liftOrder (fun v : Fin N => if P.contains v then H7 else H15) + 8 * P.length = 15 * N := by
  have hgen : ∀ (xs : List (Fin N)),
      xs.foldl (fun acc v => acc + (if P.contains v then 7 else 15)) 0 +
      8 * (xs.filter (fun v => P.contains v)).length = 15 * xs.length := by
    intro xs
    induction xs with
    | nil => simp
    | cons x xs ih =>
      simp only [List.foldl_cons, Nat.zero_add, List.filter_cons, List.length_cons]
      rw [foldl_add_shift]
      cases hc : P.contains x
      · simp only [Bool.false_eq_true, ↓reduceIte]; omega
      · simp only [↓reduceIte, List.length_cons]; omega
  have hfilt : ((List.finRange N).filter (fun v => P.contains v)).length = P.length := by
    apply len_filter_eq _ P hnd
    intro x
    simp
  have h0 := hgen (List.finRange N)
  rw [hfilt, List.length_finRange] at h0
  have heq : liftOrder (fun v : Fin N => if P.contains v then H7 else H15) =
      (List.finRange N).foldl (fun acc v => acc + (if P.contains v then 7 else 15)) 0 := by
    simp only [totalOrder]
    congr 1; funext acc v
    cases P.contains v <;> rfl
  rw [heq]; exact h0

/-- **Theorem (`f_cubic_6_4packing`)**:
    For ANY cubic base graph `B : CubicBase N` of girth `≥ 17`, lifting the greedy maximal
    4-packing `P = greedy4Pack B` (`P ↦ H_7`, `V \ P ↦ H_15`) produces a cubic simple graph of
    order `M = 15 * N - 8 * |P|` (with `M ≤ 15 * N - 8 * ((N + 45) / 46)`, e.g. `≤ 30,360` for `N = 2048`)
    that contains NO `C4`, `C8`, `C16`, `C32`, or `C64`! -/
theorem f_cubic_6_4packing {N : Nat} (B : CubicBase N)
    (hgirth : ∀ L : Nat, L < 17 → ¬ B.graph.HasCycle L) :
    let P := greedy4Pack B
    let g : Fin N → Gadget3 := fun v => if P.contains v then H7 else H15
    let G := liftGraph B g (fun _ a => a)
    liftOrder g + 8 * P.length = 15 * N ∧
    N ≤ 46 * P.length ∧
    G.IsCubic ∧
    ¬ G.HasCycle 4 ∧ ¬ G.HasCycle 8 ∧ ¬ G.HasCycle 16 ∧ ¬ G.HasCycle 32 ∧ ¬ G.HasCycle 64 := by
  intro P g G
  obtain ⟨hnd, _, _, hsep⟩ := greedy4PackAux_props B (List.finRange N) [] List.nodup_nil
    (fun _ _ ha => by simp at ha)
  have hord := liftOrder_H7_H15 P hnd
  have hpsize := greedy4Pack_size_bound B
  have hperm : ∀ u : Fin N, ∀ a b : Fin 3, (fun _ a => a) u a = (fun _ a => a) u b → a = b :=
    fun _ _ _ h => h
  have hcub : G.IsCubic := by
    apply liftGraph_isCubic B g (fun _ a => a) hperm
    intro u
    by_cases hu : P.contains u = true
    · simp only [g, hu, ↓reduceIte]; exact H7_isCubicInternal
    · simp only [g, hu]; exact H15_isCubicInternal
  have hnoT : ∀ T : Nat, T = 4 ∨ T = 8 ∨ T = 16 ∨ T = 32 ∨ T = 64 → ¬ G.HasCycle T := by
    intro T hT ⟨c⟩
    rcases liftGraph_cycle_dichotomy B g (fun _ a => a) hperm c with ⟨v, hv, _⟩ | ⟨k, C, hlen⟩
    · by_cases hvp : P.contains v = true
      · apply gadget_not_hasCycle_of_eq (show g v = H7 by simp only [g, hvp, ↓reduceIte]) _ hv
        rcases hT with rfl | rfl | rfl | rfl | rfl
        · exact H7_no_C4
        · exact H7_no_C8
        · exact not_hasCycle_of_order_lt H7.graph (by decide)
        · exact not_hasCycle_of_order_lt H7.graph (by decide)
        · exact not_hasCycle_of_order_lt H7.graph (by decide)
      · apply gadget_not_hasCycle_of_eq (show g v = H15 by simp only [g, hvp]; rfl) _ hv
        rcases hT with rfl | rfl | rfl | rfl | rfl
        · exact H15_no_C4
        · exact H15_no_C8
        · exact not_hasCycle_of_order_lt H15.graph (by decide)
        · exact not_hasCycle_of_order_lt H15.graph (by decide)
        · exact not_hasCycle_of_order_lt H15.graph (by decide)
    · have hk17 : 17 ≤ k := by
        by_cases h : k < 17
        · exfalso; exact hgirth k h ⟨C⟩
        · omega
      let inP (i : Fin k) : Bool := P.contains (C.vert i)
      have hgap : ∀ (i : Fin k) (step : Nat), 1 ≤ step → step ≤ 4 →
          inP i = true → inP ⟨(i.val + step) % k, Nat.mod_lt _ (by omega)⟩ = false := by
        intro i step hs1 hs4 hi
        by_cases hj : inP ⟨(i.val + step) % k, Nat.mod_lt _ (by omega)⟩ = true
        · exfalso
          have ha : C.vert i ∈ P := List.contains_iff_mem.mp hi
          have hb : C.vert ⟨(i.val + step) % k, Nat.mod_lt _ (by omega)⟩ ∈ P :=
            List.contains_iff_mem.mp hj
          have hne_idx : i ≠ ⟨(i.val + step) % k, Nat.mod_lt _ (by omega)⟩ := by
            intro heq
            have hv : i.val = (i.val + step) % k := congrArg Fin.val heq
            by_cases hlt : i.val + step < k
            · rw [Nat.mod_eq_of_lt hlt] at hv; omega
            · rw [Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega)] at hv; omega
          have hne_v : C.vert i ≠ C.vert ⟨(i.val + step) % k, Nat.mod_lt _ (by omega)⟩ :=
            fun h => hne_idx (C.inj _ _ h)
          let arc : SimplePath B.graph (C.vert i)
              (C.vert ⟨(i.val + step) % k, Nat.mod_lt _ (by omega)⟩) step := {
            vert := fun t => C.vert ⟨(i.val + t.val) % k, Nat.mod_lt _ (by omega)⟩
            start_eq := congrArg C.vert (Fin.ext (by simp [Nat.mod_eq_of_lt i.isLt]))
            end_eq := rfl
            inj := fun t1 t2 ht => by
              have hfin := C.inj _ _ ht
              have hv : (i.val + t1.val) % k = (i.val + t2.val) % k := congrArg Fin.val hfin
              have ht1 := t1.isLt; have ht2 := t2.isLt
              by_cases h1 : i.val + t1.val < k <;> by_cases h2 : i.val + t2.val < k
              · rw [Nat.mod_eq_of_lt h1, Nat.mod_eq_of_lt h2] at hv; exact Fin.ext (by omega)
              · rw [Nat.mod_eq_of_lt h1, Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega)] at hv
                exact Fin.ext (by omega)
              · rw [Nat.mod_eq_of_lt h2, Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega)] at hv
                exact Fin.ext (by omega)
              · rw [Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega),
                    Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega)] at hv
                exact Fin.ext (by omega)
            edge := fun t => by
              have he := C.edge ⟨(i.val + t.val) % k, Nat.mod_lt _ (by omega)⟩
              have hm : ((i.val + t.val) % k + 1) % k = (i.val + (t.val + 1)) % k := by
                rw [Nat.mod_add_mod, Nat.add_assoc]
              simpa [hm] using he
          }
          exact hsep _ _ ha hb hne_v step hs4 ⟨arc⟩
        · cases h : inP ⟨(i.val + step) % k, Nat.mod_lt _ (by omega)⟩
          · rfl
          · exact absurd h hj
      let pList := (List.finRange k).filter inP
      let shift5 (i : Fin k) : List (Fin k) :=
        (List.finRange 5).map (fun r => ⟨(i.val + r.val) % k, Nat.mod_lt _ (by omega)⟩)
      have h5_inj : ∀ i ∈ pList, ∀ j ∈ pList, ∀ r1 r2 : Fin 5,
          (⟨(i.val + r1.val) % k, Nat.mod_lt _ (by omega)⟩ : Fin k) =
          ⟨(j.val + r2.val) % k, Nat.mod_lt _ (by omega)⟩ → i = j ∧ r1 = r2 := by
        intro i hi j hj r1 r2 heq
        have hiP : inP i = true := (List.mem_filter.mp hi).2
        have hjP : inP j = true := (List.mem_filter.mp hj).2
        have hv : (i.val + r1.val) % k = (j.val + r2.val) % k := congrArg Fin.val heq
        have hr : r1 = r2 := by
          by_cases hlt : r1.val < r2.val
          · exfalso
            let step := r2.val - r1.val
            have hmod : (j.val + step) % k = i.val := by
              have hstep : (j.val + step + r1.val) % k = (i.val + r1.val) % k := by
                rw [show j.val + step + r1.val = j.val + r2.val by omega]; exact hv.symm
              let a := (j.val + step) % k
              have ha_eq : (a + r1.val) % k = (i.val + r1.val) % k := by
                rw [Nat.mod_add_mod]; exact hstep
              have ha_lt : a < k := Nat.mod_lt _ (by omega)
              by_cases h1 : a + r1.val < k <;> by_cases h2 : i.val + r1.val < k
              · rw [Nat.mod_eq_of_lt h1, Nat.mod_eq_of_lt h2] at ha_eq; omega
              · rw [Nat.mod_eq_of_lt h1, Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega)] at ha_eq; omega
              · rw [Nat.mod_eq_of_lt h2, Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega)] at ha_eq; omega
              · rw [Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega),
                    Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega)] at ha_eq; omega
            have hf := hgap j step (by omega) (by omega) hjP
            have hfin : (⟨(j.val + step) % k, Nat.mod_lt _ (by omega)⟩ : Fin k) = i := Fin.ext hmod
            rw [hfin, hiP] at hf; exact Bool.false_ne_true hf.symm
          · by_cases hgt : r2.val < r1.val
            · exfalso
              let step := r1.val - r2.val
              have hmod : (i.val + step) % k = j.val := by
                have hstep : (i.val + step + r2.val) % k = (j.val + r2.val) % k := by
                  rw [show i.val + step + r2.val = i.val + r1.val by omega]; exact hv
                let a := (i.val + step) % k
                have ha_eq : (a + r2.val) % k = (j.val + r2.val) % k := by
                  rw [Nat.mod_add_mod]; exact hstep
                have ha_lt : a < k := Nat.mod_lt _ (by omega)
                by_cases h1 : a + r2.val < k <;> by_cases h2 : j.val + r2.val < k
                · rw [Nat.mod_eq_of_lt h1, Nat.mod_eq_of_lt h2] at ha_eq; omega
                · rw [Nat.mod_eq_of_lt h1, Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega)] at ha_eq; omega
                · rw [Nat.mod_eq_of_lt h2, Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega)] at ha_eq; omega
                · rw [Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega),
                      Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega)] at ha_eq; omega
              have hf := hgap i step (by omega) (by omega) hiP
              have hfin : (⟨(i.val + step) % k, Nat.mod_lt _ (by omega)⟩ : Fin k) = j := Fin.ext hmod
              rw [hfin, hjP] at hf; exact Bool.false_ne_true hf.symm
            · exact Fin.ext (by omega)
        subst hr
        refine ⟨?_, rfl⟩
        by_cases h1 : i.val + r1.val < k <;> by_cases h2 : j.val + r1.val < k
        · rw [Nat.mod_eq_of_lt h1, Nat.mod_eq_of_lt h2] at hv; exact Fin.ext (by omega)
        · rw [Nat.mod_eq_of_lt h1, Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega)] at hv; exact Fin.ext (by omega)
        · rw [Nat.mod_eq_of_lt h2, Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega)] at hv; exact Fin.ext (by omega)
        · rw [Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega),
              Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega)] at hv; exact Fin.ext (by omega)
      have hnd_blocks : ∀ (xs : List (Fin k)), xs.Nodup → (∀ x, x ∈ xs → x ∈ pList) →
          (xs.flatMap shift5).Nodup ∧ (xs.flatMap shift5).length = 5 * xs.length := by
        intro xs
        induction xs with
        | nil => intro _ _; simp
        | cons x xs ih =>
          intro hnd_x hsub_x
          rw [List.nodup_cons] at hnd_x
          obtain ⟨hnd_tl, hlen_tl⟩ := ih hnd_x.2 (fun y hy => hsub_x y (List.mem_cons_of_mem x hy))
          have hnd_hd : (shift5 x).Nodup :=
            nodup_map_of_inj (fun r1 r2 heq => (h5_inj x (hsub_x x (List.mem_cons_self ..)) x
              (hsub_x x (List.mem_cons_self ..)) r1 r2 heq).2) (List.nodup_finRange 5)
          have hdisj : ∀ z, z ∈ shift5 x → z ∉ xs.flatMap shift5 := by
            intro z hz1 hz2
            simp only [shift5, List.mem_map, List.mem_finRange, true_and] at hz1
            obtain ⟨r1, rfl⟩ := hz1
            simp only [List.mem_flatMap, shift5, List.mem_map, List.mem_finRange, true_and] at hz2
            obtain ⟨y, hy, r2, hyr⟩ := hz2
            have hxy := (h5_inj x (hsub_x x (List.mem_cons_self ..)) y
              (hsub_x y (List.mem_cons_of_mem x hy)) r1 r2 hyr.symm).1
            exact hnd_x.1 (hxy ▸ hy)
          have hnd_app : (shift5 x ++ xs.flatMap shift5).Nodup := by
            rw [List.nodup_append]
            refine ⟨hnd_hd, hnd_tl, fun a ha b hb heq => hdisj a ha (heq ▸ hb)⟩
          refine ⟨by simpa [List.flatMap_cons] using hnd_app, ?_⟩
          simp only [List.flatMap_cons, List.length_append, shift5, List.length_map,
            List.length_finRange, List.length_cons, hlen_tl]
          omega
      obtain ⟨hnd5, hlen5⟩ := hnd_blocks pList ((List.nodup_finRange k).filter _) (fun _ h => h)
      have h5le : 5 * pList.length ≤ k := by
        have hle := nodup_len_le _ (List.finRange k) hnd5 (fun z _ => List.mem_finRange z)
        rw [hlen5, List.length_finRange] at hle
        exact hle
      have hws : 3 * k - pList.length ≤ cycleWeightSum C (liftWeight B g (fun _ a => a)) := by
        have hpt : ∀ i : Fin k,
            (if inP i then 2 else 3) ≤
            liftWeight B g (fun _ a => a)
              (C.vert ⟨(i.val + k - 1) % k, Nat.mod_lt _ (by omega)⟩)
              (C.vert i)
              (C.vert ⟨(i.val + 1) % k, Nat.mod_lt _ (by omega)⟩) := by
          intro i
          have hprev_adj : B.graph.adj (C.vert i) (C.vert ⟨(i.val + k - 1) % k, Nat.mod_lt _ (by omega)⟩) = true := by
            rw [B.graph.symm]
            have he := C.edge ⟨(i.val + k - 1) % k, Nat.mod_lt _ (by omega)⟩
            have hm : ((i.val + k - 1) % k + 1) % k = i.val := by
              rw [Nat.mod_add_mod, show i.val + k - 1 + 1 = i.val + k by omega,
                  Nat.add_mod_right, Nat.mod_eq_of_lt i.isLt]
            simpa [hm] using he
          have hnxt_adj : B.graph.adj (C.vert i) (C.vert ⟨(i.val + 1) % k, Nat.mod_lt _ (by omega)⟩) = true :=
            C.edge i
          have hne : C.vert ⟨(i.val + k - 1) % k, Nat.mod_lt _ (by omega)⟩ ≠
              C.vert ⟨(i.val + 1) % k, Nat.mod_lt _ (by omega)⟩ := by
            intro heq
            have hv : (i.val + k - 1) % k = (i.val + 1) % k := congrArg Fin.val (C.inj _ _ heq)
            by_cases hi0 : i.val = 0
            · rw [hi0, Nat.zero_add, Nat.mod_eq_of_lt (by omega), Nat.mod_eq_of_lt (by omega)] at hv; omega
            · by_cases hi1 : i.val + 1 < k
              · rw [show i.val + k - 1 = i.val - 1 + k by omega, Nat.add_mod_right,
                    Nat.mod_eq_of_lt (by omega), Nat.mod_eq_of_lt hi1] at hv; omega
              · have hie : i.val = k - 1 := by omega
                rw [hie, show k - 1 + k - 1 = (k - 2) + k by omega, Nat.add_mod_right,
                    Nat.mod_eq_of_lt (by omega), show k - 1 + 1 = k by omega, Nat.mod_self] at hv; omega
          have hep := B.edgePort_ne_of_ne hprev_adj hnxt_adj hne
          by_cases hc : P.contains (C.vert i) = true
          · simp only [liftWeight, g, inP, hc, ↓reduceIte]; exact H7_dl_ge2 _ _ hep
          · simp only [liftWeight, g, inP, hc]; exact H15_dl_ge3 _ _ hep
        have hfold_sum : ∀ (xs : List (Fin k)),
            3 * xs.length ≤
              xs.foldl (fun acc i => acc + liftWeight B g (fun _ a => a)
                (C.vert ⟨(i.val + k - 1) % k, Nat.mod_lt _ (by omega)⟩)
                (C.vert i)
                (C.vert ⟨(i.val + 1) % k, Nat.mod_lt _ (by omega)⟩)) 0 +
              (xs.filter inP).length := by
          intro xs
          induction xs with
          | nil => simp
          | cons i xs ih =>
            simp only [List.foldl_cons, Nat.zero_add, List.filter_cons, List.length_cons]
            rw [foldl_add_shift]
            have h1 := hpt i
            cases hc : inP i <;> simp only [hc, Bool.false_eq_true, ↓reduceIte, List.length_cons] at h1 ⊢ <;> omega
        have h := hfold_sum (List.finRange k)
        simp only [List.length_finRange] at h
        change 3 * k ≤ cycleWeightSum C (liftWeight B g (fun _ a => a)) + pList.length at h
        omega
      rcases hT with rfl | rfl | rfl | rfl | rfl <;> omega
  exact ⟨hord, hpsize, hcub,
    hnoT 4 (Or.inl rfl),
    hnoT 8 (Or.inr (Or.inl rfl)),
    hnoT 16 (Or.inr (Or.inr (Or.inl rfl))),
    hnoT 32 (Or.inr (Or.inr (Or.inr (Or.inl rfl)))),
    hnoT 64 (Or.inr (Or.inr (Or.inr (Or.inr rfl))))⟩

/-- Numerical corollary for any `N = 2048` cubic base of girth `≥ 17` (such as a girth-18
    cubic Cayley/coset base): yields a cubic `{C4, C8, C16, C32, C64}`-free graph of order `≤ 30,360`! -/
theorem f_cubic_6_4packing_N2048 (B : CubicBase 2048)
    (hgirth : ∀ L : Nat, L < 17 → ¬ B.graph.HasCycle L) :
    ∃ (M : Nat) (G : FinGraph M),
      M ≤ 30360 ∧ G.IsCubic ∧
      ¬ G.HasCycle 4 ∧ ¬ G.HasCycle 8 ∧ ¬ G.HasCycle 16 ∧ ¬ G.HasCycle 32 ∧ ¬ G.HasCycle 64 := by
  obtain ⟨hord, hpsize, hcub, h4, h8, h16, h32, h64⟩ := f_cubic_6_4packing B hgirth
  exact ⟨_, _, by omega, hcub, h4, h8, h16, h32, h64⟩

end Sglab
