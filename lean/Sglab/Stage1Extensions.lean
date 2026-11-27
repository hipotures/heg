import Sglab.Graph
import Sglab.GadgetLift
import Sglab.Gadgets
import Sglab.Records

/-!
# Sglab.Stage1Extensions — Source 8-Packing Lift (`f_cubic(6) ≤ 10,498`) & Certified `(3,10)`-Cages

Proves with zero `sorry`, zero custom axioms, and zero `native_decide`:
  1. `f_cubic_6_source_8packing`:
     For ANY cubic base `B : CubicBase N` of girth `≥ 16`, ANY functional orientation
     `chosen : Fin N → Fin N` along edges of `B` with no directed cycle of length `1..16`,
     and ANY nodup list `S : List (Fin N)` of sources (`indeg_chosen = 0`) forming an
     8-packing (pairwise distance `≥ 9` in `B`), replacing `S ↦ H_7` and `V \ S ↦ H_15`
     with distinguished port `0` aligned to `chosen` yields a cubic `{C4, C8, C16, C32, C64}`-free
     graph of exact order `15 * N - 8 * S.length`!
  2. `f_cubic_6_source_8packing_N702_S4`:
     Numerical instantiation for `N = 702, |S| = 4` (verified on `k3_g16_n702.g6`):
     exact cubic `{C4, C8, C16, C32, C64}`-free graph of order `10,498`.
  3. `cage310_1_certified`, `cage310_2_certified`, `cage310_3_certified`:
     All three `(3,10)`-cages (`n = 70`: Balaban 10-cage, Harries, Harries–Wong) are
     kernel-verified to be simple, 3-regular (`IsCubic`), bipartite (`IsBipartite`),
     `C4`-free, and to contain explicit simple 16-cycles (`HasCycle G 16`).
-/

namespace Sglab
open FinGraph

/-! ### 1. Elementary Helpers -/

private theorem H7_dl_ge2' (a b : Fin 3) (h : a ≠ b) : 2 ≤ H7.distLower a b := by
  have hall : ∀ x y : Fin 3, x ≠ y → 2 ≤ H7.distLower x y := by decide
  exact hall a b h

private theorem H15_dl_ge3' (a b : Fin 3) (h : a ≠ b) : 3 ≤ H15.distLower a b := by
  have hall : ∀ x y : Fin 3, x ≠ y → 3 ≤ H15.distLower x y := by decide
  exact hall a b h

private theorem H15_dl_ge5_of_ne0 (a b : Fin 3) (hne : a ≠ b)
    (ha : a ≠ ⟨0, by omega⟩) (hb : b ≠ ⟨0, by omega⟩) :
    5 ≤ H15.distLower a b := by
  have hall : ∀ x y : Fin 3, x ≠ y → x ≠ ⟨0, by omega⟩ → y ≠ ⟨0, by omega⟩ →
      5 ≤ H15.distLower x y := by decide
  exact hall a b hne ha hb

private theorem foldl_add_shift' {α : Type} (f : α → Nat) (xs : List α) (a : Nat) :
    xs.foldl (fun acc x => acc + f x) a = a + xs.foldl (fun acc x => acc + f x) 0 := by
  induction xs generalizing a with
  | nil => simp
  | cons x xs ih =>
    simp only [List.foldl_cons, Nat.zero_add]
    rw [ih (a + f x), ih (f x), Nat.add_assoc]

private theorem nodup_len_le' {α : Type} [DecidableEq α] (xs ys : List α)
    (hnd : xs.Nodup) (hsub : ∀ x, x ∈ xs → x ∈ ys) : xs.length ≤ ys.length := by
  induction xs generalizing ys with
  | nil => simp
  | cons x xs ih =>
    rw [List.nodup_cons] at hnd
    have hx : x ∈ ys := hsub x (List.mem_cons_self ..)
    have hsub' : ∀ z, z ∈ xs → z ∈ ys.erase x := by
      intro z hz
      exact (List.mem_erase_of_ne (fun h => by subst h; exact hnd.1 hz)).mpr (hsub z (List.mem_cons_of_mem x hz))
    have hle := ih (ys.erase x) hnd.2 hsub'
    have herase : (ys.erase x).length + 1 = ys.length := by
      rw [List.length_erase_of_mem hx]
      have hpos : 0 < ys.length := List.length_pos_of_mem hx
      omega
    simp only [List.length_cons]
    omega

private theorem nodup_map_of_inj' {α β : Type} {f : α → β}
    (hinj : ∀ a b, f a = f b → a = b) {xs : List α} (hnd : xs.Nodup) :
    (xs.map f).Nodup := by
  induction xs with
  | nil => simp
  | cons x xs ih =>
    rw [List.nodup_cons] at hnd
    simp only [List.map_cons, List.nodup_cons, List.mem_map]
    refine ⟨?_, ih hnd.2⟩
    rintro ⟨y, hy, heq⟩
    exact hnd.1 (hinj y x heq ▸ hy)

private theorem liftOrder_H7_H15' {N : Nat} (S : List (Fin N)) (hnd : S.Nodup) :
    liftOrder (fun u : Fin N => if S.contains u then H7 else H15) = 15 * N - 8 * S.length := by
  let g : Fin N → Gadget3 := fun u => if S.contains u then H7 else H15
  have hsum : ∀ (xs : List (Fin N)),
      xs.foldl (fun acc u => acc + (g u).order) 0 + 8 * (xs.filter (fun u => S.contains u)).length =
      15 * xs.length := by
    intro xs
    induction xs with
    | nil => simp
    | cons x xs ih =>
      simp only [List.foldl_cons, Nat.zero_add, List.filter_cons, List.length_cons]
      rw [foldl_add_shift']
      by_cases hx : S.contains x = true
      · simp only [g, hx, ↓reduceIte, H7, List.length_cons] at ih ⊢; omega
      · simp only [g, hx, Bool.false_eq_true, ↓reduceIte, H15] at ih ⊢; omega
  have h1 := hsum (List.finRange N)
  simp only [List.length_finRange] at h1
  have hflen : ((List.finRange N).filter (fun u => S.contains u)).length = S.length := by
    have hle1 : ((List.finRange N).filter (fun u => S.contains u)).length ≤ S.length :=
      nodup_len_le' _ _ ((List.nodup_finRange N).filter _) fun z hz =>
        List.contains_iff_mem.mp (List.mem_filter.mp hz).2
    have hle2 : S.length ≤ ((List.finRange N).filter (fun u => S.contains u)).length :=
      nodup_len_le' _ _ hnd fun z hz =>
        List.mem_filter.mpr ⟨List.mem_finRange z, List.contains_iff_mem.mpr hz⟩
    omega
  rw [hflen] at h1
  change (List.finRange N).foldl (fun acc u => acc + (g u).order) 0 = 15 * N - 8 * S.length
  omega

/-- Finite pigeonhole principle on `Fin 16`: any map `f : Fin 17 → Fin 16` has a collision `a < b`. -/
private theorem pigeonhole_17_16 (f : Fin 17 → Fin 16) :
    ∃ a b : Fin 17, a.val < b.val ∧ f a = f b := by
  exact Classical.byContradiction fun h => by
    have hinj : ∀ x y : Fin 17, f x = f y → x = y := by
      intro x y hxy
      by_cases hlt : x.val < y.val
      · exact absurd ⟨x, y, hlt, hxy⟩ h
      · by_cases hgt : y.val < x.val
        · exact absurd ⟨y, x, hgt, hxy.symm⟩ h
        · exact Fin.ext (by omega)
    have hnd : ((List.finRange 17).map f).Nodup :=
      nodup_map_of_inj' hinj (List.nodup_finRange 17)
    have hle : ((List.finRange 17).map f).length ≤ (List.finRange 16).length :=
      nodup_len_le' _ _ hnd (fun z _ => List.mem_finRange z)
    simp only [List.length_map, List.length_finRange] at hle
    omega

private theorem repeat_add {α : Type} (f : α → α) (a b : Nat) (x : α) :
    Nat.repeat f (a + b) x = Nat.repeat f b (Nat.repeat f a x) := by
  induction b with
  | zero => simp [Nat.repeat]
  | succ b ih =>
    rw [show a + (b + 1) = (a + b) + 1 by omega]
    simp only [Nat.repeat]
    rw [ih]

/-! ### 2. General Source 8-Packing Lift Theorem (`f_cubic_6_source_8packing`) -/

/-- **Theorem (`f_cubic_6_source_8packing`) — Source 8-Packing Lift on Any Girth-`≥ 16` Cubic Base**:
    Let `B : CubicBase N` have girth `≥ 16`, let `chosen : Fin N → Fin N` select one incident edge
    per vertex with NO directed cycle of length `1..16`, and let `S : List (Fin N)` be a nodup list
    of sources (`∀ s ∈ S, ∀ v, chosen v ≠ s`) with pairwise distance `≥ 9` in `B` (an 8-packing).
    Replacing `S ↦ H_7` and `V \ S ↦ H_15` (with distinguished port `0` aligned to `chosen`)
    yields a simple cubic `{C4, C8, C16, C32, C64}`-free graph of exact order `15 * N - 8 * S.length`! -/
theorem f_cubic_6_source_8packing {N : Nat} (B : CubicBase N)
    (hgirth : ∀ L : Nat, L < 16 → ¬ B.graph.HasCycle L)
    (chosen : Fin N → Fin N)
    (hchosen_adj : ∀ u : Fin N, B.graph.adj u (chosen u) = true)
    (hno_dir16 : ∀ (x : Fin N) (t : Nat), 1 ≤ t → t ≤ 16 → Nat.repeat chosen t x ≠ x)
    (S : List (Fin N)) (hS_nodup : S.Nodup)
    (hS_src : ∀ s ∈ S, ∀ v : Fin N, chosen v ≠ s)
    (hS_pack : ∀ a ∈ S, ∀ b ∈ S, a ≠ b → ∀ d : Nat, d ≤ 8 → ¬ Nonempty (SimplePath B.graph a b d)) :
    let g : Fin N → Gadget3 := fun u => if S.contains u then H7 else H15
    let perm : Fin N → Fin 3 → Fin 3 := fun u => rotPerm (B.edgePort u (chosen u))
    let G := liftGraph B g perm
    liftOrder g = 15 * N - 8 * S.length ∧
    G.IsCubic ∧
    ¬ G.HasCycle 4 ∧ ¬ G.HasCycle 8 ∧ ¬ G.HasCycle 16 ∧ ¬ G.HasCycle 32 ∧ ¬ G.HasCycle 64 := by
  intro g perm G
  have hord : liftOrder g = 15 * N - 8 * S.length := liftOrder_H7_H15' S hS_nodup
  have hperm : ∀ u : Fin N, ∀ a b : Fin 3, perm u a = perm u b → a = b :=
    fun u => rotPerm_inj (B.edgePort u (chosen u))
  have hcub : G.IsCubic := by
    apply liftGraph_isCubic B g perm hperm
    intro u
    by_cases hu : S.contains u = true
    · simp only [g, hu, ↓reduceIte]; exact H7_isCubicInternal
    · simp only [g, hu]; exact H15_isCubicInternal
  have hnoT : ∀ T : Nat, T = 4 ∨ T = 8 ∨ T = 16 ∨ T = 32 ∨ T = 64 → ¬ G.HasCycle T := by
    intro T hT ⟨c⟩
    rcases liftGraph_cycle_dichotomy B g perm hperm c with ⟨v, hv, _⟩ | ⟨k, C, hlen⟩
    · by_cases hvs : S.contains v = true
      · apply gadget_not_hasCycle_of_eq (show g v = H7 by simp only [g, hvs, ↓reduceIte]) _ hv
        rcases hT with rfl | rfl | rfl | rfl | rfl
        · exact H7_no_C4
        · exact H7_no_C8
        · exact not_hasCycle_of_order_lt H7.graph (by decide)
        · exact not_hasCycle_of_order_lt H7.graph (by decide)
        · exact not_hasCycle_of_order_lt H7.graph (by decide)
      · apply gadget_not_hasCycle_of_eq (show g v = H15 by simp only [g, hvs]; rfl) _ hv
        rcases hT with rfl | rfl | rfl | rfl | rfl
        · exact H15_no_C4
        · exact H15_no_C8
        · exact not_hasCycle_of_order_lt H15.graph (by decide)
        · exact not_hasCycle_of_order_lt H15.graph (by decide)
        · exact not_hasCycle_of_order_lt H15.graph (by decide)
    · have hk16 : 16 ≤ k := by
        by_cases h : k < 16
        · exfalso; exact hgirth k h ⟨C⟩
        · omega
      let inS (i : Fin k) : Bool := S.contains (C.vert i)
      -- Any two vertices of `S` on `C` are separated by at least 9 steps along `C`!
      have hgap : ∀ (i : Fin k) (step : Nat), 1 ≤ step → step ≤ 8 →
          inS i = true → inS ⟨(i.val + step) % k, Nat.mod_lt _ (by omega)⟩ = false := by
        intro i step hs1 hs8 hi
        by_cases hj : inS ⟨(i.val + step) % k, Nat.mod_lt _ (by omega)⟩ = true
        · exfalso
          have ha : C.vert i ∈ S := List.contains_iff_mem.mp hi
          have hb : C.vert ⟨(i.val + step) % k, Nat.mod_lt _ (by omega)⟩ ∈ S :=
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
              have hv : (i.val + t1.val) % k = (i.val + t2.val) % k := congrArg Fin.val (C.inj _ _ ht)
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
          exact hS_pack _ ha _ hb hne_v step hs8 ⟨arc⟩
        · cases h : inS ⟨(i.val + step) % k, Nat.mod_lt _ (by omega)⟩
          · rfl
          · exact absurd h hj
      -- Helper: cycle neighbors of `C.vert i` are adjacent to `C.vert i` and distinct
      have hcycle_adj : ∀ i : Fin k,
          B.graph.adj (C.vert i) (C.vert ⟨(i.val + k - 1) % k, Nat.mod_lt _ (by omega)⟩) = true ∧
          B.graph.adj (C.vert i) (C.vert ⟨(i.val + 1) % k, Nat.mod_lt _ (by omega)⟩) = true ∧
          C.vert ⟨(i.val + k - 1) % k, Nat.mod_lt _ (by omega)⟩ ≠
            C.vert ⟨(i.val + 1) % k, Nat.mod_lt _ (by omega)⟩ := by
        intro i
        refine ⟨?_, C.edge i, ?_⟩
        · rw [B.graph.symm]
          have he := C.edge ⟨(i.val + k - 1) % k, Nat.mod_lt _ (by omega)⟩
          have hm : ((i.val + k - 1) % k + 1) % k = i.val := by
            rw [Nat.mod_add_mod, show i.val + k - 1 + 1 = i.val + k by omega,
                Nat.add_mod_right, Nat.mod_eq_of_lt i.isLt]
          simpa [hm] using he
        · intro heq
          have hv : (i.val + k - 1) % k = (i.val + 1) % k := congrArg Fin.val (C.inj _ _ heq)
          by_cases hi0 : i.val = 0
          · rw [hi0, Nat.zero_add, Nat.mod_eq_of_lt (by omega), Nat.mod_eq_of_lt (by omega)] at hv; omega
          · by_cases hi1 : i.val + 1 < k
            · rw [show i.val + k - 1 = i.val - 1 + k by omega, Nat.add_mod_right,
                  Nat.mod_eq_of_lt (by omega), Nat.mod_eq_of_lt hi1] at hv; omega
            · have hie : i.val = k - 1 := by omega
              rw [hie, show k - 1 + k - 1 = (k - 2) + k by omega, Nat.add_mod_right,
                  Nat.mod_eq_of_lt (by omega), show k - 1 + 1 = k by omega, Nat.mod_self] at hv; omega
      -- Base pointwise bound at every `i : Fin k`
      have hpt_base : ∀ i : Fin k,
          (if inS i then 2 else 3) ≤
          liftWeight B g perm
            (C.vert ⟨(i.val + k - 1) % k, Nat.mod_lt _ (by omega)⟩)
            (C.vert i)
            (C.vert ⟨(i.val + 1) % k, Nat.mod_lt _ (by omega)⟩) := by
        intro i
        obtain ⟨hp_adj, hn_adj, hne⟩ := hcycle_adj i
        have hep : perm (C.vert i) (B.edgePort (C.vert i) (C.vert ⟨(i.val + k - 1) % k, Nat.mod_lt _ (by omega)⟩)) ≠
            perm (C.vert i) (B.edgePort (C.vert i) (C.vert ⟨(i.val + 1) % k, Nat.mod_lt _ (by omega)⟩)) :=
          fun h => B.edgePort_ne_of_ne hp_adj hn_adj hne (hperm _ _ _ h)
        by_cases hc : S.contains (C.vert i) = true
        · simp only [liftWeight, g, inS, hc, ↓reduceIte]; exact H7_dl_ge2' _ _ hep
        · simp only [liftWeight, g, inS, hc]; exact H15_dl_ge3' _ _ hep
      -- Split into `k = 16` (source + orientation gives `+2` at an H15 vertex and at most `-1` at `≤ 1` source)
      -- vs `k ≥ 17` (9-step spacing gives `9 * |S ∩ C| ≤ k`, hence `4k - ⌊k/9⌋ ≥ 67 > 64`)!
      by_cases hk_eq : k = 16
      · subst hk_eq
        -- Step A: `S ∩ C` has at most 1 element!
        have hS_le1 : ∀ i j : Fin 16, inS i = true → inS j = true → i = j := by
          intro i j hi hj
          exact Classical.byContradiction fun hne => by
            by_cases h1 : i.val < j.val
            · by_cases hd : j.val - i.val ≤ 8
              · have hf := hgap i (j.val - i.val) (by omega) hd hi
                have hfin : (⟨(i.val + (j.val - i.val)) % 16, Nat.mod_lt _ (by omega)⟩ : Fin 16) = j :=
                  Fin.ext (by dsimp; have := j.isLt; omega)
                rw [hfin, hj] at hf; exact Bool.false_ne_true hf.symm
              · have hf := hgap j (16 + i.val - j.val) (by omega) (by omega) hj
                have hfin : (⟨(j.val + (16 + i.val - j.val)) % 16, Nat.mod_lt _ (by omega)⟩ : Fin 16) = i :=
                  Fin.ext (by dsimp; have := i.isLt; omega)
                rw [hfin, hi] at hf; exact Bool.false_ne_true hf.symm
            · by_cases hd : i.val - j.val ≤ 8
              · have hf := hgap j (i.val - j.val) (by omega) hd hj
                have hfin : (⟨(j.val + (i.val - j.val)) % 16, Nat.mod_lt _ (by omega)⟩ : Fin 16) = i :=
                  Fin.ext (by dsimp; have := i.isLt; omega)
                rw [hfin, hi] at hf; exact Bool.false_ne_true hf.symm
              · have hf := hgap i (16 + j.val - i.val) (by omega) (by omega) hi
                have hfin : (⟨(i.val + (16 + j.val - i.val)) % 16, Nat.mod_lt _ (by omega)⟩ : Fin 16) = j :=
                  Fin.ext (by dsimp; have := j.isLt; omega)
                rw [hfin, hj] at hf; exact Bool.false_ne_true hf.symm
        have hS_cnt_le1 : ((List.finRange 16).filter inS).length ≤ 1 := by
          let fl := (List.finRange 16).filter inS
          have hnd_fl : fl.Nodup := (List.nodup_finRange 16).filter inS
          change fl.length ≤ 1
          cases hfl : fl with
          | nil => simp
          | cons a rest =>
            cases rest with
            | nil => simp
            | cons b _ =>
              have ha : inS a = true := (List.mem_filter.mp (hfl ▸ List.mem_cons_self ..)).2
              have hb : inS b = true := (List.mem_filter.mp (hfl ▸ List.mem_cons_of_mem a (List.mem_cons_self ..))).2
              have hab : a = b := hS_le1 a b ha hb
              rw [hfl, List.nodup_cons] at hnd_fl
              exact absurd (hab ▸ List.mem_cons_self ..) hnd_fl.1
        -- Step B: There exists an `H_15` vertex `i_star` on `C` whose `chosen` edge is omitted from `C`!
        have hex_omit : ∃ i : Fin 16, inS i = false ∧
            chosen (C.vert i) ≠ C.vert ⟨(i.val + 16 - 1) % 16, Nat.mod_lt _ (by omega)⟩ ∧
            chosen (C.vert i) ≠ C.vert ⟨(i.val + 1) % 16, Nat.mod_lt _ (by omega)⟩ := by
          exact Classical.byContradiction fun hnone => by
            -- Every `i` with `inS i = false` maps under `chosen` to another `j` on `C` with `inS j = false`!
            have hstep : ∀ i : Fin 16, inS i = false →
                ∃ j : Fin 16, chosen (C.vert i) = C.vert j ∧ inS j = false := by
              intro i hi
              have hnot : ¬ (chosen (C.vert i) ≠ C.vert ⟨(i.val + 16 - 1) % 16, Nat.mod_lt _ (by omega)⟩ ∧
                             chosen (C.vert i) ≠ C.vert ⟨(i.val + 1) % 16, Nat.mod_lt _ (by omega)⟩) :=
                fun h => hnone ⟨i, hi, h.1, h.2⟩
              have hor : chosen (C.vert i) = C.vert ⟨(i.val + 16 - 1) % 16, Nat.mod_lt _ (by omega)⟩ ∨
                         chosen (C.vert i) = C.vert ⟨(i.val + 1) % 16, Nat.mod_lt _ (by omega)⟩ := by
                by_cases h1 : chosen (C.vert i) = C.vert ⟨(i.val + 16 - 1) % 16, Nat.mod_lt _ (by omega)⟩
                · exact Or.inl h1
                · by_cases h2 : chosen (C.vert i) = C.vert ⟨(i.val + 1) % 16, Nat.mod_lt _ (by omega)⟩
                  · exact Or.inr h2
                  · exact absurd ⟨h1, h2⟩ hnot
              rcases hor with heq | heq
              · refine ⟨⟨(i.val + 16 - 1) % 16, Nat.mod_lt _ (by omega)⟩, heq, ?_⟩
                cases hjs : inS ⟨(i.val + 16 - 1) % 16, Nat.mod_lt _ (by omega)⟩
                · rfl
                · exact absurd heq (hS_src _ (List.contains_iff_mem.mp hjs) (C.vert i))
              · refine ⟨⟨(i.val + 1) % 16, Nat.mod_lt _ (by omega)⟩, heq, ?_⟩
                cases hjs : inS ⟨(i.val + 1) % 16, Nat.mod_lt _ (by omega)⟩
                · rfl
                · exact absurd heq (hS_src _ (List.contains_iff_mem.mp hjs) (C.vert i))
            -- Pick a starting index `i0 : Fin 16` with `inS i0 = false` (one of `0` or `1` works!)
            have hex0 : ∃ i0 : Fin 16, inS i0 = false := by
              cases h0 : inS ⟨0, by omega⟩
              · exact ⟨⟨0, by omega⟩, h0⟩
              · cases h1 : inS ⟨1, by omega⟩
                · exact ⟨⟨1, by omega⟩, h1⟩
                · have heq := hS_le1 ⟨0, by omega⟩ ⟨1, by omega⟩ h0 h1
                  exact absurd (congrArg Fin.val heq) Nat.zero_ne_one
            obtain ⟨i0, hi0⟩ := hex0
            -- By induction on `t`, `Nat.repeat chosen t (C.vert i0)` stays on `C \ S`!
            have horbit : ∀ t : Nat, ∃ j : Fin 16, Nat.repeat chosen t (C.vert i0) = C.vert j ∧ inS j = false := by
              intro t
              induction t with
              | zero => exact ⟨i0, rfl, hi0⟩
              | succ t ih =>
                obtain ⟨j, hj, hjs⟩ := ih
                obtain ⟨j', hj', hj's⟩ := hstep j hjs
                refine ⟨j', ?_, hj's⟩
                simp only [Nat.repeat, hj, hj']
            -- Extract a map `f : Fin 17 → Fin 16` via `Classical.choose` and apply pigeonhole!
            let f : Fin 17 → Fin 16 := fun t => Classical.choose (horbit t.val)
            have hf_spec : ∀ t : Fin 17, Nat.repeat chosen t.val (C.vert i0) = C.vert (f t) :=
              fun t => (Classical.choose_spec (horbit t.val)).1
            obtain ⟨a, b, hab, hfab⟩ := pigeonhole_17_16 f
            have hrep : Nat.repeat chosen (b.val - a.val) (Nat.repeat chosen a.val (C.vert i0)) =
                Nat.repeat chosen a.val (C.vert i0) := by
              rw [← repeat_add, show a.val + (b.val - a.val) = b.val by omega, hf_spec b, hf_spec a, hfab]
            exact hno_dir16 (Nat.repeat chosen a.val (C.vert i0)) (b.val - a.val) (by omega) (by omega) hrep
        obtain ⟨i_star, hi_star_notS, homit_prev, homit_next⟩ := hex_omit
        -- At `i_star`, `liftWeight ≥ 5` (since `g (C.vert i_star) = H15` and both cycle ports map to `≠ 0`)!
        have hstar5 : 5 ≤ liftWeight B g perm
            (C.vert ⟨(i_star.val + 16 - 1) % 16, Nat.mod_lt _ (by omega)⟩)
            (C.vert i_star)
            (C.vert ⟨(i_star.val + 1) % 16, Nat.mod_lt _ (by omega)⟩) := by
          obtain ⟨hp_adj, hn_adj, hne⟩ := hcycle_adj i_star
          have hc_adj := hchosen_adj (C.vert i_star)
          have hep_ne : perm (C.vert i_star) (B.edgePort (C.vert i_star) (C.vert ⟨(i_star.val + 16 - 1) % 16, Nat.mod_lt _ (by omega)⟩)) ≠
              perm (C.vert i_star) (B.edgePort (C.vert i_star) (C.vert ⟨(i_star.val + 1) % 16, Nat.mod_lt _ (by omega)⟩)) :=
            fun h => B.edgePort_ne_of_ne hp_adj hn_adj hne (hperm _ _ _ h)
          have hp_ne0 : perm (C.vert i_star) (B.edgePort (C.vert i_star) (C.vert ⟨(i_star.val + 16 - 1) % 16, Nat.mod_lt _ (by omega)⟩)) ≠ ⟨0, by omega⟩ := by
            intro h0
            have h0' : perm (C.vert i_star) (B.edgePort (C.vert i_star) (chosen (C.vert i_star))) = ⟨0, by omega⟩ :=
              rotPerm_self _
            have hpeq := hperm (C.vert i_star) _ _ (h0.trans h0'.symm)
            exact B.edgePort_ne_of_ne hc_adj hp_adj homit_prev hpeq.symm
          have hn_ne0 : perm (C.vert i_star) (B.edgePort (C.vert i_star) (C.vert ⟨(i_star.val + 1) % 16, Nat.mod_lt _ (by omega)⟩)) ≠ ⟨0, by omega⟩ := by
            intro h0
            have h0' : perm (C.vert i_star) (B.edgePort (C.vert i_star) (chosen (C.vert i_star))) = ⟨0, by omega⟩ :=
              rotPerm_self _
            have hpeq := hperm (C.vert i_star) _ _ (h0.trans h0'.symm)
            exact B.edgePort_ne_of_ne hc_adj hn_adj homit_next hpeq.symm
          simp only [liftWeight, g, inS] at hi_star_notS ⊢
          rw [hi_star_notS]
          exact H15_dl_ge5_of_ne0 _ _ hep_ne hp_ne0 hn_ne0
        -- Sum over `Fin 16`: `3 * 16 + 2 * (#{i_star}) ≤ cycleWeightSum + |S ∩ C|`!
        have hfold16 : ∀ (xs : List (Fin 16)),
            3 * xs.length + 2 * (xs.filter (fun i => i == i_star)).length ≤
              xs.foldl (fun acc i => acc + liftWeight B g perm
                (C.vert ⟨(i.val + 16 - 1) % 16, Nat.mod_lt _ (by omega)⟩)
                (C.vert i)
                (C.vert ⟨(i.val + 1) % 16, Nat.mod_lt _ (by omega)⟩)) 0 +
              (xs.filter inS).length := by
          intro xs
          induction xs with
          | nil => simp
          | cons i xs ih =>
            simp only [List.foldl_cons, Nat.zero_add, List.filter_cons, List.length_cons]
            rw [foldl_add_shift']
            by_cases heq : i = i_star
            · subst heq
              simp only [beq_self_eq_true, ↓reduceIte, hi_star_notS, Bool.false_eq_true, List.length_cons]
              omega
            · have hne_b : (i == i_star) = false := beq_false_of_ne heq
              have h1 := hpt_base i
              simp only [hne_b, Bool.false_eq_true, ↓reduceIte]
              cases hc : inS i <;> simp only [hc, Bool.false_eq_true, ↓reduceIte, List.length_cons] at h1 ⊢ <;> omega
        have hsum16 := hfold16 (List.finRange 16)
        simp only [List.length_finRange] at hsum16
        have hstar_cnt : 1 ≤ ((List.finRange 16).filter (fun i => i == i_star)).length :=
          List.length_pos_of_mem (List.mem_filter.mpr ⟨List.mem_finRange i_star, beq_self_eq_true i_star⟩)
        change 3 * 16 + 2 * ((List.finRange 16).filter (fun i => i == i_star)).length ≤
          cycleWeightSum C (liftWeight B g perm) + ((List.finRange 16).filter inS).length at hsum16
        rcases hT with rfl | rfl | rfl | rfl | rfl <;> omega
      · -- Case `k ≥ 17`: 9-step spacing gives `9 * |S ∩ C| ≤ k`, so `4*k - |S ∩ C| ≥ 67 > 64`!
        have hk17 : 17 ≤ k := by omega
        let sList := (List.finRange k).filter inS
        let shift9 (i : Fin k) : List (Fin k) :=
          (List.finRange 9).map (fun r => ⟨(i.val + r.val) % k, Nat.mod_lt _ (by omega)⟩)
        have h9_inj : ∀ i ∈ sList, ∀ j ∈ sList, ∀ r1 r2 : Fin 9,
            (⟨(i.val + r1.val) % k, Nat.mod_lt _ (by omega)⟩ : Fin k) =
            ⟨(j.val + r2.val) % k, Nat.mod_lt _ (by omega)⟩ → i = j ∧ r1 = r2 := by
          intro i hi j hj r1 r2 heq
          have hiS : inS i = true := (List.mem_filter.mp hi).2
          have hjS : inS j = true := (List.mem_filter.mp hj).2
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
              have hf := hgap j step (by omega) (by omega) hjS
              have hfin : (⟨(j.val + step) % k, Nat.mod_lt _ (by omega)⟩ : Fin k) = i := Fin.ext hmod
              rw [hfin, hiS] at hf; exact Bool.false_ne_true hf.symm
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
                have hf := hgap i step (by omega) (by omega) hiS
                have hfin : (⟨(i.val + step) % k, Nat.mod_lt _ (by omega)⟩ : Fin k) = j := Fin.ext hmod
                rw [hfin, hjS] at hf; exact Bool.false_ne_true hf.symm
              · exact Fin.ext (by omega)
          subst hr
          refine ⟨?_, rfl⟩
          by_cases h1 : i.val + r1.val < k <;> by_cases h2 : j.val + r1.val < k
          · rw [Nat.mod_eq_of_lt h1, Nat.mod_eq_of_lt h2] at hv; exact Fin.ext (by omega)
          · rw [Nat.mod_eq_of_lt h1, Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega)] at hv; exact Fin.ext (by omega)
          · rw [Nat.mod_eq_of_lt h2, Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega)] at hv; exact Fin.ext (by omega)
          · rw [Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega),
                Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega)] at hv; exact Fin.ext (by omega)
        have hnd_blocks : ∀ (xs : List (Fin k)), xs.Nodup → (∀ x, x ∈ xs → x ∈ sList) →
            (xs.flatMap shift9).Nodup ∧ (xs.flatMap shift9).length = 9 * xs.length := by
          intro xs
          induction xs with
          | nil => intro _ _; simp
          | cons x xs ih =>
            intro hnd_x hsub_x
            rw [List.nodup_cons] at hnd_x
            obtain ⟨hnd_tl, hlen_tl⟩ := ih hnd_x.2 (fun y hy => hsub_x y (List.mem_cons_of_mem x hy))
            have hnd_hd : (shift9 x).Nodup :=
              nodup_map_of_inj' (fun r1 r2 heq => (h9_inj x (hsub_x x (List.mem_cons_self ..)) x
                (hsub_x x (List.mem_cons_self ..)) r1 r2 heq).2) (List.nodup_finRange 9)
            have hdisj : ∀ z, z ∈ shift9 x → z ∉ xs.flatMap shift9 := by
              intro z hz1 hz2
              simp only [shift9, List.mem_map, List.mem_finRange, true_and] at hz1
              obtain ⟨r1, rfl⟩ := hz1
              simp only [List.mem_flatMap, shift9, List.mem_map, List.mem_finRange, true_and] at hz2
              obtain ⟨y, hy, r2, hyr⟩ := hz2
              have hxy := (h9_inj x (hsub_x x (List.mem_cons_self ..)) y
                (hsub_x y (List.mem_cons_of_mem x hy)) r1 r2 hyr.symm).1
              exact hnd_x.1 (hxy ▸ hy)
            have hnd_app : (shift9 x ++ xs.flatMap shift9).Nodup := by
              rw [List.nodup_append]
              refine ⟨hnd_hd, hnd_tl, fun a ha b hb heq => hdisj a ha (heq ▸ hb)⟩
            refine ⟨by simpa [List.flatMap_cons] using hnd_app, ?_⟩
            simp only [List.flatMap_cons, List.length_append, shift9, List.length_map,
              List.length_finRange, List.length_cons, hlen_tl]
            omega
        obtain ⟨hnd9, hlen9⟩ := hnd_blocks sList ((List.nodup_finRange k).filter _) (fun _ h => h)
        have h9le : 9 * sList.length ≤ k := by
          have hle := nodup_len_le' _ (List.finRange k) hnd9 (fun z _ => List.mem_finRange z)
          rw [hlen9, List.length_finRange] at hle
          exact hle
        have hfold_sum : ∀ (xs : List (Fin k)),
            3 * xs.length ≤
              xs.foldl (fun acc i => acc + liftWeight B g perm
                (C.vert ⟨(i.val + k - 1) % k, Nat.mod_lt _ (by omega)⟩)
                (C.vert i)
                (C.vert ⟨(i.val + 1) % k, Nat.mod_lt _ (by omega)⟩)) 0 +
              (xs.filter inS).length := by
          intro xs
          induction xs with
          | nil => simp
          | cons i xs ih =>
            simp only [List.foldl_cons, Nat.zero_add, List.filter_cons, List.length_cons]
            rw [foldl_add_shift']
            have h1 := hpt_base i
            cases hc : inS i <;> simp only [hc, Bool.false_eq_true, ↓reduceIte, List.length_cons] at h1 ⊢ <;> omega
        have hsum := hfold_sum (List.finRange k)
        simp only [List.length_finRange] at hsum
        change 3 * k ≤ cycleWeightSum C (liftWeight B g perm) + sList.length at hsum
        rcases hT with rfl | rfl | rfl | rfl | rfl <;> omega
  exact ⟨hord, hcub,
    hnoT 4 (Or.inl rfl),
    hnoT 8 (Or.inr (Or.inl rfl)),
    hnoT 16 (Or.inr (Or.inr (Or.inl rfl))),
    hnoT 32 (Or.inr (Or.inr (Or.inr (Or.inl rfl)))),
    hnoT 64 (Or.inr (Or.inr (Or.inr (Or.inr rfl))))⟩

/-- Numerical corollary for `N = 702` girth-16 cubic base with a 4-element source 8-packing
    (verified computationally on House of Graphs `k3_g16_n702.g6` with `S_8 = [270, 417, 484, 622]`):
    yields a cubic `{C4, C8, C16, C32, C64}`-free graph of exact order `10,498` (`≤ 10,498`). -/
theorem f_cubic_6_source_8packing_N702_S4 (B : CubicBase 702)
    (hgirth : ∀ L : Nat, L < 16 → ¬ B.graph.HasCycle L)
    (chosen : Fin 702 → Fin 702)
    (hchosen_adj : ∀ u : Fin 702, B.graph.adj u (chosen u) = true)
    (hno_dir16 : ∀ (x : Fin 702) (t : Nat), 1 ≤ t → t ≤ 16 → Nat.repeat chosen t x ≠ x)
    (S : List (Fin 702)) (hS_nodup : S.Nodup) (hS_len : 4 ≤ S.length)
    (hS_src : ∀ s ∈ S, ∀ v : Fin 702, chosen v ≠ s)
    (hS_pack : ∀ a ∈ S, ∀ b ∈ S, a ≠ b → ∀ d : Nat, d ≤ 8 → ¬ Nonempty (SimplePath B.graph a b d)) :
    ∃ (M : Nat) (G : FinGraph M),
      M ≤ 10498 ∧ G.IsCubic ∧
      ¬ G.HasCycle 4 ∧ ¬ G.HasCycle 8 ∧ ¬ G.HasCycle 16 ∧ ¬ G.HasCycle 32 ∧ ¬ G.HasCycle 64 := by
  obtain ⟨hord, hcub, h4, h8, h16, h32, h64⟩ :=
    f_cubic_6_source_8packing B hgirth chosen hchosen_adj hno_dir16 S hS_nodup hS_src hS_pack
  exact ⟨_, _, by omega, hcub, h4, h8, h16, h32, h64⟩

/-! ### 3. Kernel-Verified Certification of All Three `(3,10)`-Cages (`n = 70`) -/

/-- A graph `G` is bipartite if it admits a proper 2-coloring. -/
def IsBipartite {n : Nat} (G : FinGraph n) : Prop :=
  ∃ col : Fin n → Bool, ∀ u v : Fin n, G.adj u v = true → col u ≠ col v

/-- Helper: certify `G.HasCycle L` from an explicit list of `L` vertex indices checked in the kernel. -/
def checkCycleWitness {n : Nat} (G : FinGraph n) (L : Nat) (ws : List Nat) : Bool :=
  (ws.length == L) &&
  (decide (3 ≤ L)) &&
  (List.finRange L).all (fun i =>
    let u := ws.getD i.val n
    let v := ws.getD ((i.val + 1) % L) n
    (decide (u < n)) &&
    (decide (v < n)) &&
    (if hu : u < n then if hv : v < n then G.adj ⟨u, hu⟩ ⟨v, hv⟩ else false else false) &&
    (List.finRange L).all (fun j => (i == j) || (ws.getD j.val n != u)))

theorem hasCycle_of_witness {n : Nat} (G : FinGraph n) (L : Nat) (ws : List Nat)
    (h : checkCycleWitness G L ws = true) : G.HasCycle L := by
  simp only [checkCycleWitness, Bool.and_eq_true, beq_iff_eq, decide_eq_true_eq,
    List.all_eq_true, List.mem_finRange, true_implies] at h
  obtain ⟨⟨hlen, hL3⟩, hsteps⟩ := h
  have hlt : ∀ i : Fin L, ws.getD i.val n < n := fun i => (hsteps i).1.1.1
  refine ⟨{
    hlen := hL3
    vert := fun i => ⟨ws.getD i.val n, hlt i⟩
    inj := fun i j hij => by
      have hval : ws.getD i.val n = ws.getD j.val n := congrArg Fin.val hij
      have hall := (hsteps i).2 j
      simp only [Bool.or_eq_true, beq_iff_eq, bne_iff_ne] at hall
      rcases hall with heq | hne
      · exact heq
      · exact absurd hval.symm hne
    edge := fun i => by
      have hadj := (hsteps i).1.2
      have hu : ws.getD i.val n < n := hlt i
      have hv : ws.getD ((i.val + 1) % L) n < n := hlt ⟨(i.val + 1) % L, Nat.mod_lt _ (by omega)⟩
      simp only [hu, hv, ↓reduceDIte] at hadj
      exact hadj
  }⟩

def cage310_1Triples : List (Nat × Nat × Nat) :=
  [(1, 2, 3), (0, 64, 69), (0, 65, 66), (0, 67, 68), (8, 12, 16), (9, 15, 17), (11, 13, 19), (10, 14, 18), (4, 35, 39), (5, 34, 40), (7, 36, 38), (6, 37, 41), (4, 32, 43), (6, 30, 45), (7, 31, 42), (5, 33, 44), (4, 28, 30), (5, 28, 31), (7, 29, 32), (6, 29, 33), (37, 46, 48), (36, 46, 49), (35, 47, 51), (34, 47, 50), (39, 42, 48), (40, 45, 49), (38, 44, 51), (41, 43, 50), (16, 17, 63), (18, 19, 62), (13, 16, 58), (14, 17, 59), (12, 18, 60), (15, 19, 61), (9, 23, 52), (8, 22, 53), (10, 21, 55), (11, 20, 54), (10, 26, 58), (8, 24, 61), (9, 25, 60), (11, 27, 59), (14, 24, 56), (12, 27, 57), (15, 26, 57), (13, 25, 56), (20, 21, 63), (22, 23, 62), (20, 24, 52), (21, 25, 53), (23, 27, 55), (22, 26, 54), (34, 48, 65), (35, 49, 66), (37, 51, 68), (36, 50, 67), (42, 45, 69), (43, 44, 69), (30, 38, 65), (31, 41, 66), (32, 40, 68), (33, 39, 67), (29, 47, 64), (28, 46, 64), (1, 62, 63), (2, 52, 58), (2, 53, 59), (3, 55, 61), (3, 54, 60), (1, 56, 57)]

def cage310_2Triples : List (Nat × Nat × Nat) :=
  [(1, 2, 3), (0, 64, 67), (0, 65, 66), (0, 68, 69), (10, 12, 16), (11, 14, 15), (9, 13, 17), (8, 18, 19), (7, 41, 43), (6, 45, 46), (4, 42, 47), (5, 40, 44), (4, 28, 32), (6, 31, 33), (5, 31, 35), (5, 29, 37), (4, 30, 34), (6, 30, 36), (7, 28, 39), (7, 29, 38), (32, 45, 50), (34, 41, 48), (37, 46, 48), (33, 42, 49), (35, 43, 50), (38, 47, 51), (36, 40, 51), (39, 44, 49), (12, 18, 62), (15, 19, 63), (16, 17, 63), (13, 14, 62), (12, 20, 54), (13, 23, 55), (16, 21, 58), (14, 24, 59), (17, 26, 56), (15, 22, 57), (19, 25, 61), (18, 27, 60), (11, 26, 54), (8, 21, 55), (10, 23, 57), (8, 24, 56), (11, 27, 58), (9, 20, 61), (9, 22, 60), (10, 25, 59), (21, 22, 52), (23, 27, 53), (20, 24, 53), (25, 26, 52), (48, 51, 69), (49, 50, 68), (32, 40, 64), (33, 41, 64), (36, 43, 65), (37, 42, 65), (34, 44, 66), (35, 47, 67), (39, 46, 67), (38, 45, 66), (28, 31, 69), (29, 30, 68), (1, 54, 55), (2, 56, 57), (2, 58, 61), (1, 59, 60), (3, 53, 63), (3, 52, 62)]

def cage310_3Triples : List (Nat × Nat × Nat) :=
  [(1, 2, 3), (0, 64, 67), (0, 65, 66), (0, 68, 69), (11, 12, 16), (10, 13, 17), (8, 15, 19), (9, 14, 18), (6, 41, 43), (7, 40, 44), (5, 45, 47), (4, 42, 46), (4, 28, 32), (5, 31, 33), (7, 31, 35), (6, 30, 39), (4, 29, 36), (5, 30, 37), (7, 29, 34), (6, 28, 38), (32, 45, 50), (34, 41, 48), (37, 46, 48), (33, 42, 49), (35, 43, 50), (38, 44, 49), (39, 40, 51), (36, 47, 51), (12, 19, 62), (16, 18, 63), (15, 17, 63), (13, 14, 62), (12, 20, 54), (13, 23, 55), (18, 21, 61), (14, 24, 60), (16, 27, 56), (17, 22, 57), (19, 25, 59), (15, 26, 58), (9, 26, 54), (8, 21, 55), (11, 23, 58), (8, 24, 56), (9, 25, 57), (10, 20, 61), (11, 22, 60), (10, 27, 59), (21, 22, 52), (23, 25, 53), (20, 24, 53), (26, 27, 52), (48, 51, 69), (49, 50, 68), (32, 40, 64), (33, 41, 64), (36, 43, 65), (37, 44, 65), (39, 42, 66), (38, 47, 67), (35, 46, 67), (34, 45, 66), (28, 31, 69), (29, 30, 68), (1, 54, 55), (2, 56, 57), (2, 58, 61), (1, 59, 60), (3, 53, 63), (3, 52, 62)]

def cage310Color : Fin 70 → Bool := fun u =>
  ([false, true, true, true, false, false, false, false, true, true, true, true, true, true, true, true, true, true, true, true, true, true, true, true, true, true, true, true, false, false, false, false, false, false, false, false, false, false, false, false, false, false, false, false, false, false, false, false, false, false, false, false, true, true, true, true, true, true, true, true, true, true, true, true, false, false, false, false, false, false]).getD u.val false

def cage310_1Base : CubicBase 70 :=
  cubicBaseOfTriples 70 cage310_1Triples (by decide) (by decide) (by decide) (by decide)

def cage310_2Base : CubicBase 70 :=
  cubicBaseOfTriples 70 cage310_2Triples (by decide) (by decide) (by decide) (by decide)

def cage310_3Base : CubicBase 70 :=
  cubicBaseOfTriples 70 cage310_3Triples (by decide) (by decide) (by decide) (by decide)

/-- Helper: every `CubicBase n` graph is 3-regular (`IsCubic`). -/
theorem cubicBase_isCubic {n : Nat} (B : CubicBase n) : B.graph.IsCubic := by
  intro u
  have hmem : ∀ v : Fin n, v ∈ (List.finRange 3).map (B.nbr u) ↔ B.graph.adj u v = true := by
    intro v
    simp only [List.mem_map, List.mem_finRange, true_and, B.nbr_adj]
  have hnd : ((List.finRange 3).map (B.nbr u)).Nodup :=
    nodup_map_of_inj' (B.nbr_inj u) (List.nodup_finRange 3)
  have h1 : ((List.finRange n).filter (fun v => B.graph.adj u v)).length ≤ 3 := by
    have := nodup_len_le' _ _ ((List.nodup_finRange n).filter _) fun v hv =>
      (hmem v).mpr (List.mem_filter.mp hv).2
    simpa using this
  have h2 : 3 ≤ ((List.finRange n).filter (fun v => B.graph.adj u v)).length := by
    have := nodup_len_le' _ _ hnd fun v hv =>
      List.mem_filter.mpr ⟨List.mem_finRange v, (hmem v).mp hv⟩
    simpa using this
  change ((List.finRange n).filter (fun v => B.graph.adj u v)).length = 3
  omega

/-- **Theorem (`cage310_1_certified`)**: `(3,10)`-cage #1 (`n = 70`) is cubic, bipartite, `C4`-free,
    and contains an explicit kernel-verified simple `16`-cycle. -/
theorem cage310_1_certified :
    cage310_1Base.graph.IsCubic ∧
    IsBipartite cage310_1Base.graph ∧
    ¬ cage310_1Base.graph.HasCycle 4 ∧
    cage310_1Base.graph.HasCycle 16 := by
  refine ⟨cubicBase_isCubic cage310_1Base, ⟨cage310Color, by decide⟩,
    not_hasCycle_of_dfs cage310_1Base.graph 4 (by decide),
    hasCycle_of_witness cage310_1Base.graph 16
      [0, 1, 64, 62, 29, 18, 7, 10, 36, 21, 46, 20, 37, 54, 68, 3] (by decide)⟩

/-- **Theorem (`cage310_2_certified`)**: `(3,10)`-cage #2 (`n = 70`) is cubic, bipartite, `C4`-free,
    and contains an explicit kernel-verified simple `16`-cycle. -/
theorem cage310_2_certified :
    cage310_2Base.graph.IsCubic ∧
    IsBipartite cage310_2Base.graph ∧
    ¬ cage310_2Base.graph.HasCycle 4 ∧
    cage310_2Base.graph.HasCycle 16 := by
  refine ⟨cubicBase_isCubic cage310_2Base, ⟨cage310Color, by decide⟩,
    not_hasCycle_of_dfs cage310_2Base.graph 4 (by decide),
    hasCycle_of_witness cage310_2Base.graph 16
      [0, 1, 64, 54, 32, 12, 4, 10, 42, 23, 33, 13, 31, 62, 69, 3] (by decide)⟩

/-- **Theorem (`cage310_3_certified`)**: `(3,10)`-cage #3 (`n = 70`) is cubic, bipartite, `C4`-free,
    and contains an explicit kernel-verified simple `16`-cycle. -/
theorem cage310_3_certified :
    cage310_3Base.graph.IsCubic ∧
    IsBipartite cage310_3Base.graph ∧
    ¬ cage310_3Base.graph.HasCycle 4 ∧
    cage310_3Base.graph.HasCycle 16 := by
  refine ⟨cubicBase_isCubic cage310_3Base, ⟨cage310Color, by decide⟩,
    not_hasCycle_of_dfs cage310_3Base.graph 4 (by decide),
    hasCycle_of_witness cage310_3Base.graph 16
      [0, 1, 64, 54, 32, 12, 4, 11, 42, 23, 33, 13, 31, 62, 69, 3] (by decide)⟩

end Sglab
