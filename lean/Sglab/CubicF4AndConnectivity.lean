import Sglab.Graph
import Sglab.GadgetLift
import Sglab.Gadgets
import Sglab.Records

/-!
# Sglab.CubicF4AndConnectivity — `f_cubic(4) ≤ 78` & General 2-Connectivity of Gadget Lifts

Proves with zero Mathlib, zero `sorry`, zero custom axioms, and zero `native_decide`:
  1. `FinGraph.Is2Connected`: formal vertex-deletion connectivity (`3 ≤ n` and removing ANY
     vertex `w` leaves `G \ {w}` connected) + provably sound iterative reachability checker
     `is2Connected_of_check`.
  2. `liftGraph_is2Connected`: Master 2-Connectivity Preservation Theorem — if `B : CubicBase n`
     is 2-connected and every gadget `g u` is either 2-connected (`(g u).graph.Is2Connected`)
     or the unexpanded unit node (`(g u).isUnit = true`), then `liftGraph B g perm` is
     2-connected!
  3. **`f_cubic_4_le_78`**: kernel-verified 78-vertex strictly 3-regular, 2-connected
     `{C4, C8, C16}`-free graph (`Petersen + 1·H_15 + 9·H_7`).
  4. **2-Connectivity Certificates** for all our headline witnesses in `Sglab.Records`:
     `pet73v1_is2Connected`, `pet73v2_is2Connected`,
     `tc345_is2Connected`, `tc370_is2Connected`.
-/

namespace Sglab
open FinGraph

/-! ### 1. Formal 2-Connectivity (`ReachableAvoiding` and `Is2Connected`) -/

/-- `ReachableAvoiding G w u v` holds if `u` and `v` are connected by a walk in `G \ {w}`. -/
inductive ReachableAvoiding {n : Nat} (G : FinGraph n) (w u : Fin n) : Fin n → Prop where
  | refl (hu : u ≠ w) : ReachableAvoiding G w u u
  | step {x y : Fin n} (h : ReachableAvoiding G w u x)
      (hadj : G.adj x y = true) (hy : y ≠ w) : ReachableAvoiding G w u y

theorem ReachableAvoiding.trans {n : Nat} {G : FinGraph n} {w u x y : Fin n}
    (h1 : ReachableAvoiding G w u x) (h2 : ReachableAvoiding G w x y) :
    ReachableAvoiding G w u y := by
  induction h2 with
  | refl _ => exact h1
  | step _ hadj hy ih => exact ReachableAvoiding.step ih hadj hy

theorem ReachableAvoiding.symm {n : Nat} {G : FinGraph n} {w u v : Fin n}
    (h : ReachableAvoiding G w u v) : ReachableAvoiding G w v u := by
  induction h with
  | refl hu => exact ReachableAvoiding.refl hu
  | @step x y hux hadj hy ih =>
    have hx : x ≠ w := by
      cases hux with
      | refl hu => exact hu
      | step _ _ hx' => exact hx'
    have hstep : ReachableAvoiding G w y x :=
      ReachableAvoiding.step (ReachableAvoiding.refl hy) (by rw [G.symm]; exact hadj) hx
    exact hstep.trans ih

/-- A graph `G` on `n` vertices is **2-connected** if `n ≥ 3` and deleting any single vertex `w`
    leaves every pair of remaining vertices connected. -/
def FinGraph.Is2Connected {n : Nat} (G : FinGraph n) : Prop :=
  3 ≤ n ∧ ∀ (w u v : Fin n), u ≠ w → v ≠ w → ReachableAvoiding G w u v

theorem castGraph_is2Connected {a b : Nat} (h : a = b) (G : FinGraph a) (hG : G.Is2Connected) :
    (castGraph h G).Is2Connected := by
  subst h; exact hG

/-! ### 2. Provably Sound Kernel Checker for `Is2Connected` -/

/-- One frontier-expansion step in `G \ {w}` represented by a boolean membership function. -/
def reachStep {n : Nat} (G : FinGraph n) (w : Fin n) (vis : Fin n → Bool) (v : Fin n) : Bool :=
  (v != w) && (vis v || (List.finRange n).any (fun x => vis x && G.adj x v))

/-- Iterate `reachStep` `k` times from initial root `r`. -/
def reachIter {n : Nat} (G : FinGraph n) (w r : Fin n) : Nat → (Fin n → Bool)
  | 0 => fun v => (v == r) && (v != w)
  | k + 1 => reachStep G w (reachIter G w r k)

/-- Check `Is2Connected G` by running `n` BFS expansion steps from a root `r ≠ w` for every `w`. -/
def check2Conn {n : Nat} (G : FinGraph n) : Bool :=
  decide (3 ≤ n) &&
  (List.finRange n).all (fun w =>
    if h3 : 3 ≤ n then
      let r : Fin n := if w.val == 0 then ⟨1, by omega⟩ else ⟨0, by omega⟩
      let vis := reachIter G w r n
      (List.finRange n).all (fun v => (v == w) || vis v)
    else false)

theorem reachIter_sound {n : Nat} (G : FinGraph n) (w r : Fin n) (hr : r ≠ w) :
    ∀ (k : Nat) (v : Fin n), reachIter G w r k v = true → ReachableAvoiding G w r v := by
  intro k
  induction k with
  | zero =>
    intro v hv
    simp only [reachIter, Bool.and_eq_true, beq_iff_eq, bne_iff_ne] at hv
    rw [hv.1]; exact ReachableAvoiding.refl hr
  | succ k ih =>
    intro v hv
    simp only [reachIter, reachStep, Bool.and_eq_true, Bool.or_eq_true, bne_iff_ne,
      List.any_eq_true, List.mem_finRange, true_and] at hv
    obtain ⟨hvw, hbase | ⟨x, hx, hadj⟩⟩ := hv
    · exact ih v hbase
    · exact ReachableAvoiding.step (ih x hx) hadj hvw

theorem is2Connected_of_check {n : Nat} (G : FinGraph n) (h : check2Conn G = true) :
    G.Is2Connected := by
  simp only [check2Conn, Bool.and_eq_true, decide_eq_true_eq, List.all_eq_true,
    List.mem_finRange, true_implies] at h
  obtain ⟨h3, hall⟩ := h
  refine ⟨h3, fun w u v hu hv => ?_⟩
  have hw := hall w
  simp only [h3, ↓reduceDIte, List.all_eq_true, List.mem_finRange, true_implies,
    Bool.or_eq_true, beq_iff_eq] at hw
  let r : Fin n := if w.val = 0 then ⟨1, by omega⟩ else ⟨0, by omega⟩
  have hr : r ≠ w := by
    intro heq
    by_cases hw0 : w.val = 0
    · have hrv : r.val = 1 := by simp [r, hw0]
      have := congrArg Fin.val heq; omega
    · have hrv : r.val = 0 := by simp [r, hw0]
      have := congrArg Fin.val heq; omega
  have hru : ReachableAvoiding G w r u := by
    rcases hw u with heq | hvis
    · exact absurd heq hu
    · exact reachIter_sound G w r hr n u hvis
  have hrv : ReachableAvoiding G w r v := by
    rcases hw v with heq | hvis
    · exact absurd heq hv
    · exact reachIter_sound G w r hr n v hvis
  exact hru.symm.trans hrv

/-! ### 3. Kernel-Verified 2-Connectivity of All Gadgets & Base Graphs -/

theorem H7_is2Connected : H7.graph.Is2Connected := is2Connected_of_check H7.graph (by decide)
theorem H8star_is2Connected : H8star.graph.Is2Connected := is2Connected_of_check H8star.graph (by decide)
theorem H15_is2Connected : H15.graph.Is2Connected := is2Connected_of_check H15.graph (by decide)
theorem petersen_is2Connected : petersenBase.graph.Is2Connected :=
  is2Connected_of_check petersenBase.graph (by decide)
theorem tutteCoxeter_is2Connected : tutteCoxeterBase.graph.Is2Connected :=
  is2Connected_of_check tutteCoxeterBase.graph (by decide)

/-! ### 4. Master 2-Connectivity Preservation Theorem (`liftGraph_is2Connected`) -/

/-- Helper: lift an internal edge of gadget `g u` into `liftGraph B g perm`. -/
private theorem liftGraph_adj_internal {n : Nat} (B : CubicBase n) (g : Fin n → Gadget3)
    (perm : Fin n → Fin 3 → Fin 3) (u : Fin n) (x y : Fin (g u).order)
    (hxy : (g u).graph.adj x y = true) :
    (liftGraph B g perm).adj (encode u x) (encode u y) = true := by
  rw [liftGraph_adj_eq]
  simp only [liftAdjCoord, ↓reduceDIte]
  exact hxy

/-- Helper: lift a base edge `(u, v)` into `liftGraph B g perm` between its two port vertices. -/
private theorem liftGraph_adj_bridge {n : Nat} (B : CubicBase n) (g : Fin n → Gadget3)
    (perm : Fin n → Fin 3 → Fin 3) (u v : Fin n) (huv : B.graph.adj u v = true) :
    (liftGraph B g perm).adj
      (encode u ((g u).port (perm u (B.edgePort u v))))
      (encode v ((g v).port (perm v (B.edgePort v u)))) = true := by
  have hne : u ≠ v := fun h => by rw [h, B.graph.loopless] at huv; cases huv
  rw [liftGraph_adj_eq]
  simp only [liftAdjCoord, hne, ↓reduceDIte, huv, beq_self_eq_true, Bool.and_self]

private theorem lift_reach_intact {n : Nat} (B : CubicBase n) (g : Fin n → Gadget3)
    (perm : Fin n → Fin 3 → Fin 3) (w : Fin (liftOrder g)) (u : Fin n)
    (hne_w : ∀ z : Fin (g u).order, encode u z ≠ w)
    (z x y : Fin (g u).order) (hr : ReachableAvoiding (g u).graph z x y) :
    ReachableAvoiding (liftGraph B g perm) w (encode u x) (encode u y) := by
  induction hr with
  | refl _ => exact ReachableAvoiding.refl (hne_w x)
  | step _ hadj _ ih =>
    exact ReachableAvoiding.step ih (liftGraph_adj_internal B g perm u _ _ hadj) (hne_w _)

/-- Helper: every gadget `g u` that is either 2-connected or `isUnit = true` is connected
    inside `liftGraph B g perm \ {w}` whenever `w` lies in a different base vertex (`uw ≠ u`). -/
private theorem gadget_connected {n : Nat} (B : CubicBase n) (g : Fin n → Gadget3)
    (perm : Fin n → Fin 3 → Fin 3)
    (hg : ∀ u : Fin n, (g u).graph.Is2Connected ∨ (g u).isUnit = true)
    (w : Fin (liftOrder g)) (u : Fin n)
    (huw : (decode (fun v => (g v).order) w).1 ≠ u)
    (x y : Fin (g u).order) :
    ReachableAvoiding (liftGraph B g perm) w (encode u x) (encode u y) := by
  have hne_w : ∀ z : Fin (g u).order, encode u z ≠ w := by
    intro z heq
    have hw_eq := encode_decode (fun v => (g v).order) w
    have h1 := (encode_inj (heq.trans hw_eq.symm)).1
    exact huw h1.symm
  rcases hg u with ⟨h3, h2c⟩ | hunit
  · have hex_z : ∃ z : Fin (g u).order, z ≠ x ∧ z ≠ y := by
      by_cases h0x : x.val = 0
      · by_cases h1y : y.val = 1
        · exact ⟨⟨2, by omega⟩, fun h => by have := congrArg Fin.val h; dsimp at this; omega,
            fun h => by have := congrArg Fin.val h; dsimp at this; omega⟩
        · exact ⟨⟨1, by omega⟩, fun h => by have := congrArg Fin.val h; dsimp at this; omega,
            fun h => h1y (congrArg Fin.val h).symm⟩
      · by_cases h0y : y.val = 0
        · by_cases h1x : x.val = 1
          · exact ⟨⟨2, by omega⟩, fun h => by have := congrArg Fin.val h; dsimp at this; omega,
              fun h => by have := congrArg Fin.val h; dsimp at this; omega⟩
          · exact ⟨⟨1, by omega⟩, fun h => h1x (congrArg Fin.val h).symm,
              fun h => by have := congrArg Fin.val h; dsimp at this; omega⟩
        · exact ⟨⟨0, by omega⟩, fun h => h0x (congrArg Fin.val h).symm,
            fun h => h0y (congrArg Fin.val h).symm⟩
    obtain ⟨z, hzx, hzy⟩ := hex_z
    exact lift_reach_intact B g perm w u hne_w z x y (h2c z x y hzx.symm hzy.symm)
  · have h1 := (g u).unit_order hunit
    have hxy : x = y := Fin.ext (by have := x.isLt; have := y.isLt; omega)
    subst hxy
    exact ReachableAvoiding.refl (hne_w x)

/-- Helper: lift `ReachableAvoiding (g u).graph xw x y` inside a single gadget `g u` to `liftGraph B g perm \ {w}`. -/
private theorem lift_internal_reach {n : Nat} (B : CubicBase n) (g : Fin n → Gadget3)
    (perm : Fin n → Fin 3 → Fin 3) (w : Fin (liftOrder g))
    (u : Fin n) (xw : Fin (g u).order) (hw : encode u xw = w)
    (x y : Fin (g u).order) (hr : ReachableAvoiding (g u).graph xw x y) :
    ReachableAvoiding (liftGraph B g perm) w (encode u x) (encode u y) := by
  induction hr with
  | refl hx =>
    exact ReachableAvoiding.refl (fun heq => hx (Fin.ext (encode_inj (heq.trans hw.symm)).2))
  | step _ hadj hy ih =>
    exact ReachableAvoiding.step ih (liftGraph_adj_internal B g perm u _ _ hadj)
      (fun heq => hy (Fin.ext (encode_inj (heq.trans hw.symm)).2))

/-- **Master 2-Connectivity Preservation Theorem (`liftGraph_is2Connected`)**:
    If `B : CubicBase n` is 2-connected and every gadget `g u` is either 2-connected or
    the unexpanded 1-vertex gadget `U_1` (`isUnit = true`), then `liftGraph B g perm`
    is 2-connected! -/
theorem liftGraph_is2Connected {n : Nat} (B : CubicBase n) (g : Fin n → Gadget3)
    (perm : Fin n → Fin 3 → Fin 3)
    (hperm : ∀ u : Fin n, ∀ a b : Fin 3, perm u a = perm u b → a = b)
    (hB : B.graph.Is2Connected)
    (hg : ∀ u : Fin n, (g u).graph.Is2Connected ∨ (g u).isUnit = true) :
    (liftGraph B g perm).Is2Connected := by
  have hord_ge : n ≤ liftOrder g := by
    have hfold : ∀ xs : List (Fin n), xs.length ≤ xs.foldl (fun acc u => acc + (g u).order) 0 := by
      intro xs
      induction xs with
      | nil => simp
      | cons u xs ih =>
        simp only [List.foldl_cons, Nat.zero_add, List.length_cons]
        rw [foldl_add_shift]
        have := (g u).hpos
        omega
    simpa [liftOrder, totalOrder] using hfold (List.finRange n)
  refine ⟨by have := hB.1; omega, fun w a b ha hb => ?_⟩
  -- Unpack `decode` of `w, a, b` as genuine variables (so `subst` works cleanly!)
  have hw_eq : encode (decode (fun v => (g v).order) w).1 (decode (fun v => (g v).order) w).2 = w :=
    encode_decode _ w
  have ha_eq : encode (decode (fun v => (g v).order) a).1 (decode (fun v => (g v).order) a).2 = a :=
    encode_decode _ a
  have hb_eq : encode (decode (fun v => (g v).order) b).1 (decode (fun v => (g v).order) b).2 = b :=
    encode_decode _ b
  rcases hdw : decode (fun v => (g v).order) w with ⟨uw, xw⟩
  rcases hda : decode (fun v => (g v).order) a with ⟨ua, xa⟩
  rcases hdb : decode (fun v => (g v).order) b with ⟨ub, xb⟩
  rw [hdw] at hw_eq
  rw [hda] at ha_eq
  rw [hdb] at hb_eq
  -- Helper A: lift any `ReachableAvoiding B.graph uw u1 u2` to reachability between ANY `(u1, x1)` and `(u2, x2)`!
  have hlift_base : ∀ (u1 u2 : Fin n) (x1 : Fin (g u1).order) (x2 : Fin (g u2).order),
      u1 ≠ uw → u2 ≠ uw →
      ReachableAvoiding (liftGraph B g perm) w (encode u1 x1) (encode u2 x2) := by
    intro u1 u2 x1 x2 hu1 hu2
    have hbase := hB.2 uw u1 u2 hu1 hu2
    have haux : ∀ (v : Fin n), ReachableAvoiding B.graph uw u1 v →
        ∀ (xv : Fin (g v).order),
          ReachableAvoiding (liftGraph B g perm) w (encode u1 x1) (encode v xv) := by
      intro v hrv
      induction hrv with
      | refl _ =>
        intro xu
        exact gadget_connected B g perm hg w u1 (by rw [hdw]; exact hu1.symm) x1 xu
      | @step p q _ hpq hqw ih =>
        intro xq
        have hto_port := ih ((g p).port (perm p (B.edgePort p q)))
        have hbridge := liftGraph_adj_bridge B g perm p q hpq
        have hq_ne_w : encode q ((g q).port (perm q (B.edgePort q p))) ≠ w := by
          intro heq
          exact hqw (encode_inj (heq.trans hw_eq.symm)).1
        have hstep := ReachableAvoiding.step hto_port hbridge hq_ne_w
        have hfin := gadget_connected B g perm hg w q (by rw [hdw]; exact hqw.symm)
          ((g q).port (perm q (B.edgePort q p))) xq
        exact hstep.trans hfin
    exact haux u2 hbase x2
  -- Helper B: any remaining vertex `(uw, x)` inside `g uw` (`x ≠ xw`) reaches an intact adjacent gadget `v ≠ uw`!
  have hescape : ∀ (x : Fin (g uw).order), encode uw x ≠ w →
      ∃ (v : Fin n) (y : Fin (g v).order), v ≠ uw ∧
        ReachableAvoiding (liftGraph B g perm) w (encode uw x) (encode v y) := by
    intro x hxw
    have hx_ne_xw : x ≠ xw := fun h => hxw (by rw [h]; exact hw_eq)
    rcases hg uw with ⟨h3, h2c⟩ | hunit
    · have hnu : (g uw).isUnit = false := by
        cases hu : (g uw).isUnit
        · rfl
        · have := (g uw).unit_order hu; omega
      have hex_k : ∃ k : Fin 3, (g uw).port (perm uw k) ≠ xw := by
        by_cases h0 : (g uw).port (perm uw ⟨0, by decide⟩) = xw
        · refine ⟨⟨1, by decide⟩, fun h => ?_⟩
          have hpeq := (g uw).port_inj hnu _ _ (h.trans h0.symm)
          have := hperm uw _ _ hpeq
          exact absurd (congrArg Fin.val this) (by decide)
        · exact ⟨⟨0, by decide⟩, h0⟩
      obtain ⟨k, hk⟩ := hex_k
      have hreach_in := h2c xw x ((g uw).port (perm uw k)) hx_ne_xw hk
      have hlift_in := lift_internal_reach B g perm w uw xw hw_eq x _ hreach_in
      let v := B.nbr uw k
      have huv : B.graph.adj uw v = true := (B.nbr_adj uw v).mpr ⟨k, rfl⟩
      have hv_ne : v ≠ uw := fun h => by rw [h, B.graph.loopless] at huv; cases huv
      have hep : B.edgePort uw v = k := B.edgePort_nbr uw k
      have hbridge : (liftGraph B g perm).adj
          (encode uw ((g uw).port (perm uw k)))
          (encode v ((g v).port (perm v (B.edgePort v uw)))) = true := by
        rw [← hep]; exact liftGraph_adj_bridge B g perm uw v huv
      have hv_ne_w : encode v ((g v).port (perm v (B.edgePort v uw))) ≠ w := by
        intro heq; exact hv_ne (encode_inj (heq.trans hw_eq.symm)).1
      exact ⟨v, (g v).port (perm v (B.edgePort v uw)), hv_ne,
        ReachableAvoiding.step hlift_in hbridge hv_ne_w⟩
    · exfalso
      have h1 := (g uw).unit_order hunit
      exact hx_ne_xw (Fin.ext (by have := x.isLt; have := xw.isLt; omega))
  -- Combine cases on `ua = uw` vs `ua ≠ uw` and `ub = uw` vs `ub ≠ uw`!
  rw [← ha_eq, ← hb_eq]
  rw [← ha_eq] at ha
  rw [← hb_eq] at hb
  by_cases hua : ua = uw <;> by_cases hub : ub = uw
  · subst hua; subst hub
    have hxa : xa ≠ xw := fun h => ha (by rw [h]; exact hw_eq)
    have hxb : xb ≠ xw := fun h => hb (by rw [h]; exact hw_eq)
    rcases hg ub with ⟨_, h2c⟩ | hunit
    · exact lift_internal_reach B g perm w ub xw hw_eq xa xb (h2c xw xa xb hxa hxb)
    · exfalso
      have h1 := (g ub).unit_order hunit
      exact hxa (Fin.ext (by have := xa.isLt; have := xw.isLt; omega))
  · subst hua
    obtain ⟨v, y, hvu, hreach_v⟩ := hescape xa ha
    exact hreach_v.trans (hlift_base v ub y xb hvu hub)
  · subst hub
    obtain ⟨v, y, hvu, hreach_v⟩ := hescape xb hb
    exact (hlift_base ua v xa y hua hvu).trans hreach_v.symm
  · exact hlift_base ua ub xa xb hua hub

/-! ### 5. New Kernel-Verified Record: `f_cubic(4) ≤ 78` (`Petersen + 1·H_15 + 9·H_7`) -/

def pet78Gadget (v : Fin 10) : Gadget3 :=
  if v.val == 0 then H15 else H7

def pet78Choice : List Nat := [0, 0, 0, 1, 2, 2, 0, 1, 0, 2]

def pet78Perm (v : Fin 10) : Fin 3 → Fin 3 :=
  rotPerm ⟨(pet78Choice.getD v.val 0) % 3, Nat.mod_lt _ (by omega)⟩

theorem pet78_order : liftOrder pet78Gadget = 78 := by decide

theorem pet78_check :
    petersenBase.graph.checkWeightedCycles
      (liftWeight petersenBase pet78Gadget pet78Perm) 10 17 = true := by
  decide

theorem gadget_is2Connected_of_eq {g1 g2 : Gadget3} (h : g1 = g2) (h2 : g2.graph.Is2Connected) :
    g1.graph.Is2Connected := by
  subst h; exact h2

/-- **Headline Theorem (`f_cubic_4_le_78`)**:
    There exists a **78-vertex**, **2-connected**, **3-regular (`IsCubic`)** simple graph
    avoiding `{C4, C8, C16}` (built as `Petersen + 1·H_15 + 9·H_7`)! -/
theorem f_cubic_4_le_78 :
    ∃ G : FinGraph 78,
      G.Is2Connected ∧ G.IsCubic ∧
      ¬ G.HasCycle 4 ∧ ¬ G.HasCycle 8 ∧ ¬ G.HasCycle 16 := by
  let G0 := liftGraph petersenBase pet78Gadget pet78Perm
  have hperm : ∀ u : Fin 10, ∀ a b : Fin 3, pet78Perm u a = pet78Perm u b → a = b :=
    fun u => rotPerm_inj _
  have h2c : G0.Is2Connected := by
    apply liftGraph_is2Connected petersenBase pet78Gadget pet78Perm hperm petersen_is2Connected
    intro u
    by_cases hu : (u.val == 0) = true
    · exact Or.inl (gadget_is2Connected_of_eq (by simp [pet78Gadget, hu]) H15_is2Connected)
    · exact Or.inl (gadget_is2Connected_of_eq (by simp [pet78Gadget, hu]) H7_is2Connected)
  have hcub : G0.IsCubic := by
    apply liftGraph_isCubic petersenBase pet78Gadget pet78Perm hperm
    intro u
    by_cases hu : (u.val == 0) = true
    · simp only [pet78Gadget, hu, ↓reduceIte]; exact H15_isCubicInternal
    · simp only [pet78Gadget, hu, Bool.false_eq_true, ↓reduceIte]; exact H7_isCubicInternal
  have hno : ∀ T : Nat, T = 4 ∨ T = 8 ∨ T = 16 → ¬ G0.HasCycle T := by
    intro T hT
    apply liftGraph_no_cycle_all petersenBase pet78Gadget pet78Perm hperm T 17
      (by rcases hT with rfl | rfl | rfl <;> omega)
    · intro v
      by_cases hv : (v.val == 0) = true
      · apply gadget_not_hasCycle_of_eq (show pet78Gadget v = H15 by simp [pet78Gadget, hv])
        rcases hT with rfl | rfl | rfl
        · exact H15_no_C4
        · exact H15_no_C8
        · exact not_hasCycle_of_order_lt H15.graph (by decide)
      · apply gadget_not_hasCycle_of_eq (show pet78Gadget v = H7 by simp [pet78Gadget, hv])
        rcases hT with rfl | rfl | rfl
        · exact H7_no_C4
        · exact H7_no_C8
        · exact not_hasCycle_of_order_lt H7.graph (by decide)
    · exact pet78_check
  exact ⟨castGraph pet78_order G0,
    castGraph_is2Connected pet78_order G0 h2c,
    castGraph_isCubic pet78_order G0 hcub,
    castGraph_not_hasCycle pet78_order G0 (hno 4 (Or.inl rfl)),
    castGraph_not_hasCycle pet78_order G0 (hno 8 (Or.inr (Or.inl rfl))),
    castGraph_not_hasCycle pet78_order G0 (hno 16 (Or.inr (Or.inr rfl)))⟩

/-! ### 6. 2-Connectivity Certificates for Headline Witnesses (`73`, `73_alt`, `345`, `370`) -/

theorem pet73v1_is2Connected :
    (castGraph pet73v1_order (liftGraph petersenBase pet73v1Gadget pet73v1Perm)).Is2Connected := by
  apply castGraph_is2Connected pet73v1_order
  apply liftGraph_is2Connected petersenBase pet73v1Gadget pet73v1Perm (fun _ => rotPerm_inj _)
    petersen_is2Connected
  intro u
  by_cases hu : u.val < 3
  · exact Or.inl (gadget_is2Connected_of_eq (by simp [pet73v1Gadget, hu]) H8star_is2Connected)
  · exact Or.inl (gadget_is2Connected_of_eq (by simp [pet73v1Gadget, hu]) H7_is2Connected)

theorem pet73v2_is2Connected :
    (castGraph pet73v2_order (liftGraph petersenBase pet73v2Gadget pet73v2Perm)).Is2Connected := by
  apply castGraph_is2Connected pet73v2_order
  apply liftGraph_is2Connected petersenBase pet73v2Gadget pet73v2Perm (fun _ => rotPerm_inj _)
    petersen_is2Connected
  intro u
  by_cases hu : (u.val == 0) = true
  · exact Or.inr (by simp [pet73v2Gadget, hu, unitGadget])
  · exact Or.inl (gadget_is2Connected_of_eq (by simp [pet73v2Gadget, hu]) H8star_is2Connected)

theorem tc345_is2Connected :
    (castGraph tc345_order (liftGraph tutteCoxeterBase tc345Gadget tc345Perm)).Is2Connected := by
  apply castGraph_is2Connected tc345_order
  apply liftGraph_is2Connected tutteCoxeterBase tc345Gadget tc345Perm (fun _ => rotPerm_inj _)
    tutteCoxeter_is2Connected
  intro u
  by_cases hu : (tc345Type.getD u.val 2 == 2) = true
  · exact Or.inl (gadget_is2Connected_of_eq (by simp only [tc345Gadget, hu, ↓reduceIte]) H15_is2Connected)
  · exact Or.inl (gadget_is2Connected_of_eq (by simp only [tc345Gadget, hu, Bool.false_eq_true, ↓reduceIte]) H8star_is2Connected)

theorem tc370_is2Connected :
    (castGraph tc370_order (liftGraph tutteCoxeterBase tc370Gadget tc370Perm)).Is2Connected := by
  apply castGraph_is2Connected tc370_order
  apply liftGraph_is2Connected tutteCoxeterBase tc370Gadget tc370Perm (fun _ => rotPerm_inj _)
    tutteCoxeter_is2Connected
  intro u
  by_cases hu : (tc370Type.getD u.val 2 == 2) = true
  · exact Or.inl (gadget_is2Connected_of_eq (by simp only [tc370Gadget, hu, ↓reduceIte]) H15_is2Connected)
  · exact Or.inl (gadget_is2Connected_of_eq (by simp only [tc370Gadget, hu, Bool.false_eq_true, ↓reduceIte]) H7_is2Connected)

end Sglab
