import Sglab.Graph

/-!
# Sglab.GadgetLift — The Master 3-Port Vertex-Replacement Gadget-Lift Theorem

Formalizes the general 3-port vertex-replacement lift of any cubic base graph `B`
by a family of 3-port gadgets (including optional unexpanded 1-vertex `U_1` nodes),
proving with zero `sorry` and zero custom axioms:
  1. Simplicity, exact total order `∑_v |H_v|`, minimum degree `≥ 3`, and 3-regularity.
  2. **3-Port Cycle Projection & Length Lower Bound (`liftGraph_cycle_dichotomy`)**:
     Every simple cycle of length `L` in the lifted graph either lies entirely inside
     one gadget `H_v` (hence `HasCycle H_v L` and `L ≤ |H_v|`), OR projects via
     3-port pigeonhole onto a simple cycle `C` of length `k ≥ 3` in the base graph `B`
     satisfying `L ≥ k + ∑_{i : Fin k} distLower_{C(i)}(in_i, out_i)`.
-/

namespace Sglab
open FinGraph

/-! ### 1. Finite Disjoint Union Bijection `Σ v : Fin n, Fin (f v) ≃ Fin (totalOrder f)` -/

/-- Sum of `f u` over all `u : Fin n`. -/
def totalOrder {n : Nat} (f : Fin n → Nat) : Nat :=
  (List.finRange n).foldl (fun a u => a + f u) 0

/-- Sum of `f u` for `u.val < k`. -/
def prefixSum {n : Nat} (f : Fin n → Nat) : Nat → Nat
  | 0 => 0
  | k + 1 => if hk : k < n then prefixSum f k + f ⟨k, hk⟩ else prefixSum f k

theorem prefixSum_mono {n : Nat} (f : Fin n → Nat) {a b : Nat} (h : a ≤ b) :
    prefixSum f a ≤ prefixSum f b := by
  induction b with
  | zero =>
    have : a = 0 := by omega
    rw [this]; exact Nat.le_refl _
  | succ b ih =>
    by_cases hab : a ≤ b
    · have h1 := ih hab
      simp only [prefixSum]
      split <;> omega
    · have : a = b + 1 := by omega
      rw [this]; exact Nat.le_refl _

theorem prefixSum_eq_take_foldl {n : Nat} (f : Fin n → Nat) (k : Nat) (hk : k ≤ n) :
    prefixSum f k = ((List.finRange n).take k).foldl (fun a u => a + f u) 0 := by
  induction k with
  | zero => simp [prefixSum]
  | succ k ih =>
    have hkn : k < n := by omega
    have htake : (List.finRange n).take (k + 1) = (List.finRange n).take k ++ [⟨k, hkn⟩] := by
      apply List.ext_getElem
      · simp; omega
      · intro idx h1 h2
        by_cases hlt : idx < k
        · rw [List.getElem_append_left (by simp; omega)]; simp
        · have heq : idx = k := by simp at h1; omega
          subst heq
          rw [List.getElem_append_right (by simp; omega)]
          simp
    rw [htake, List.foldl_append, foldl_add_shift, ← ih (by omega)]
    simp [prefixSum, hkn]

theorem prefixSum_n {n : Nat} (f : Fin n → Nat) :
    prefixSum f n = totalOrder f := by
  rw [prefixSum_eq_take_foldl f n (Nat.le_refl n)]
  rw [List.take_of_length_le (by simp)]
  rfl

theorem prefixSum_add_lt {n : Nat} (f : Fin n → Nat) (v : Fin n) (x : Fin (f v)) :
    prefixSum f v.val + x.val < totalOrder f := by
  rw [← prefixSum_n f]
  have h1 : prefixSum f (v.val + 1) = prefixSum f v.val + f v := by
    simp [prefixSum, v.isLt]
  have h2 : prefixSum f (v.val + 1) ≤ prefixSum f n := prefixSum_mono f (by omega)
  omega

/-- Encode `(v, x)` into `Fin (totalOrder f)`. -/
def encode {n : Nat} {f : Fin n → Nat} (v : Fin n) (x : Fin (f v)) : Fin (totalOrder f) :=
  ⟨prefixSum f v.val + x.val, prefixSum_add_lt f v x⟩

theorem encode_inj {n : Nat} {f : Fin n → Nat} {v1 v2 : Fin n}
    {x1 : Fin (f v1)} {x2 : Fin (f v2)}
    (h : encode v1 x1 = encode v2 x2) :
    v1 = v2 ∧ x1.val = x2.val := by
  have hval : prefixSum f v1.val + x1.val = prefixSum f v2.val + x2.val := congrArg Fin.val h
  by_cases hlt : v1.val < v2.val
  · have h1 : prefixSum f (v1.val + 1) = prefixSum f v1.val + f v1 := by simp [prefixSum, v1.isLt]
    have h2 : prefixSum f (v1.val + 1) ≤ prefixSum f v2.val := prefixSum_mono f (by omega)
    have hx1 := x1.isLt
    omega
  · by_cases hgt : v2.val < v1.val
    · have h1 : prefixSum f (v2.val + 1) = prefixSum f v2.val + f v2 := by simp [prefixSum, v2.isLt]
      have h2 : prefixSum f (v2.val + 1) ≤ prefixSum f v1.val := prefixSum_mono f (by omega)
      have hx2 := x2.isLt
      omega
    · have hv : v1 = v2 := Fin.ext (by omega)
      subst hv
      exact ⟨rfl, by omega⟩

/-- Decode `z : Fin (totalOrder f)` back into `(v, x)` by linear scan over `0..n-1`. -/
def decodeAux {n : Nat} (f : Fin n → Nat) :
    (k : Nat) → (hk : k ≤ n) → (z : Nat) → (hz : z < prefixSum f k) →
    Σ v : Fin n, Fin (f v)
  | 0, _, _, hz => by simp [prefixSum] at hz
  | k + 1, hk, z, hz =>
    if hlt : z < prefixSum f k then
      decodeAux f k (by omega) z hlt
    else
      have hkn : k < n := by omega
      have hps : prefixSum f (k + 1) = prefixSum f k + f ⟨k, hkn⟩ := by simp [prefixSum, hkn]
      ⟨⟨k, hkn⟩, ⟨z - prefixSum f k, by omega⟩⟩

theorem encode_decodeAux {n : Nat} (f : Fin n → Nat) :
    ∀ (k : Nat) (hk : k ≤ n) (z : Nat) (hz : z < prefixSum f k),
      (encode (decodeAux f k hk z hz).1 (decodeAux f k hk z hz).2).val = z
  | 0, _, _, hz => by simp [prefixSum] at hz
  | k + 1, hk, z, hz => by
    simp only [decodeAux]
    by_cases hlt : z < prefixSum f k
    · rw [dite_eq_left hlt]
      exact encode_decodeAux f k (by omega) z hlt
    · rw [dite_eq_right hlt]
      simp only [encode]
      omega

/-- Value-preserving cast between `Fin a` and `Fin b`. -/
def castFin {a b : Nat} (h : a = b) (x : Fin a) : Fin b :=
  ⟨x.val, h ▸ x.isLt⟩

theorem encode_eq_of_val {n : Nat} {f : Fin n → Nat} {v1 v2 : Fin n}
    {x1 : Fin (f v1)} {x2 : Fin (f v2)}
    (hv : v1 = v2) (hx : x1.val = x2.val) :
    encode v1 x1 = encode v2 x2 := by
  subst hv
  apply Fin.ext
  simp [encode, hx]

theorem nodup_map_of_inj {α β : Type} {f : α → β} (hinj : ∀ a b, f a = f b → a = b)
    {xs : List α} (hnd : xs.Nodup) : (xs.map f).Nodup := by
  induction xs with
  | nil => simp
  | cons x xs ih =>
    rw [List.nodup_cons] at hnd
    rw [List.map_cons, List.nodup_cons]
    refine ⟨?_, ih hnd.2⟩
    intro hm
    rw [List.mem_map] at hm
    obtain ⟨y, hy, hfy⟩ := hm
    exact hnd.1 (hinj y x hfy ▸ hy)

/-- Decode `z : Fin (totalOrder f)` into its unique `(v, x)` coordinates. -/
def decode {n : Nat} (f : Fin n → Nat) (z : Fin (totalOrder f)) : Σ v : Fin n, Fin (f v) :=
  decodeAux f n (Nat.le_refl n) z.val (by rw [prefixSum_n]; exact z.isLt)

theorem encode_decode {n : Nat} (f : Fin n → Nat) (z : Fin (totalOrder f)) :
    encode (decode f z).1 (decode f z).2 = z := by
  apply Fin.ext
  exact encode_decodeAux f n (Nat.le_refl n) z.val _

theorem decode_encode {n : Nat} {f : Fin n → Nat} (v : Fin n) (x : Fin (f v)) :
    decode f (encode v x) = ⟨v, x⟩ := by
  have heq := encode_decode f (encode v x)
  obtain ⟨hv, hx⟩ := encode_inj heq
  cases hd : decode f (encode v x) with
  | mk v' x' =>
    rw [hd] at hv hx
    simp only at hv hx
    subst hv
    congr 1
    exact Fin.ext hx

/-! ### 2. Cubic Base Frames and 3-Port Gadgets -/

/-- A cubic base graph `B` equipped with an explicit 3-neighbor frame `nbr : Fin n → Fin 3 → Fin n`. -/
structure CubicBase (n : Nat) where
  graph : FinGraph n
  nbr : Fin n → Fin 3 → Fin n
  nbr_inj : ∀ u : Fin n, ∀ a b : Fin 3, nbr u a = nbr u b → a = b
  nbr_adj : ∀ u v : Fin n, graph.adj u v = true ↔ ∃ a : Fin 3, nbr u a = v

namespace CubicBase

/-- The unique port index `a : Fin 3` at `u` pointing to neighbor `v` (defaults to `0` if non-adjacent). -/
def edgePort {n : Nat} (B : CubicBase n) (u v : Fin n) : Fin 3 :=
  if B.nbr u 0 == v then 0
  else if B.nbr u 1 == v then 1
  else 2

theorem nbr_edgePort {n : Nat} (B : CubicBase n) {u v : Fin n} (h : B.graph.adj u v = true) :
    B.nbr u (B.edgePort u v) = v := by
  obtain ⟨a, ha⟩ := (B.nbr_adj u v).mp h
  simp only [edgePort]
  by_cases h0 : B.nbr u 0 = v
  · simp [h0]
  · by_cases h1 : B.nbr u 1 = v
    · simp [h0, h1]
    · simp only [beq_iff_eq, h0, h1, ↓reduceIte]
      have ha2 : a = 2 := by
        have : a.val = 0 ∨ a.val = 1 ∨ a.val = 2 := by omega
        rcases this with h' | h' | h'
        · exfalso; apply h0; rw [← ha]; congr 1; exact Fin.ext h'.symm
        · exfalso; apply h1; rw [← ha]; congr 1; exact Fin.ext h'.symm
        · exact Fin.ext h'
      rw [← ha2]; exact ha

theorem edgePort_nbr {n : Nat} (B : CubicBase n) (u : Fin n) (a : Fin 3) :
    B.edgePort u (B.nbr u a) = a := by
  have hadj : B.graph.adj u (B.nbr u a) = true := (B.nbr_adj u (B.nbr u a)).mpr ⟨a, rfl⟩
  exact B.nbr_inj u _ _ (B.nbr_edgePort hadj)

theorem edgePort_ne_of_ne {n : Nat} (B : CubicBase n) {u v1 v2 : Fin n}
    (h1 : B.graph.adj u v1 = true) (h2 : B.graph.adj u v2 = true) (hne : v1 ≠ v2) :
    B.edgePort u v1 ≠ B.edgePort u v2 := by
  intro heq
  have hv1 := B.nbr_edgePort h1
  have hv2 := B.nbr_edgePort h2
  rw [heq] at hv1
  exact hne (hv1.symm.trans hv2)

end CubicBase

/-- A 3-port vertex-replacement gadget (either a standard 3-port gadget with 3 distinct
    ports of internal degree 2 and internal vertices of degree `≥ 3`, or the 1-vertex
    unexpanded node `U_1` with `isUnit = true`, `order = 1`, `distLower = 0`). -/
structure Gadget3 where
  order : Nat
  hpos : 0 < order
  graph : FinGraph order
  port : Fin 3 → Fin order
  isUnit : Bool
  port_inj : isUnit = false → ∀ a b : Fin 3, port a = port b → a = b
  unit_order : isUnit = true → order = 1
  distLower : Fin 3 → Fin 3 → Nat
  distLower_symm : ∀ a b : Fin 3, distLower a b = distLower b a
  distLower_sound : ∀ (a b : Fin 3) (d : Nat), a ≠ b →
    graph.SimplePath (port a) (port b) d → distLower a b ≤ d
  deg_ok : isUnit = false →
    (∀ a : Fin 3, graph.deg (port a) = 2) ∧
    (∀ x : Fin order, (∀ a : Fin 3, x ≠ port a) → 3 ≤ graph.deg x)

/-- Optional cubic property for a 3-port gadget (every internal non-port has degree 3). -/
def Gadget3.IsCubicInternal (g : Gadget3) : Prop :=
  g.isUnit = true ∨ ∀ x : Fin g.order, (∀ a : Fin 3, x ≠ g.port a) → g.graph.deg x = 3

/-- The trivial 1-vertex unexpanded gadget `U_1` (`order = 1`, `distLower = 0`). -/
def unitGadget : Gadget3 where
  order := 1
  hpos := by omega
  graph := {
    adj := fun _ _ => false
    symm := fun _ _ => rfl
    loopless := fun _ => rfl
  }
  port := fun _ => ⟨0, by omega⟩
  isUnit := true
  port_inj := by intro h; simp at h
  unit_order := fun _ => rfl
  distLower := fun _ _ => 0
  distLower_symm := fun _ _ => rfl
  distLower_sound := fun _ _ _ _ _ => Nat.zero_le _
  deg_ok := by intro h; simp at h

/-! ### 3. The Lifted Graph `liftGraph` and Degree Preservation -/

/-- Total vertex count of lifting base `B` with gadgets `g`. -/
abbrev liftOrder {n : Nat} (g : Fin n → Gadget3) : Nat :=
  totalOrder (fun v => (g v).order)

/-- Adjacency predicate on decoded coordinates `(u, x)` and `(v, y)`. -/
def liftAdjCoord {n : Nat} (B : CubicBase n) (g : Fin n → Gadget3)
    (perm : Fin n → Fin 3 → Fin 3)
    (u : Fin n) (x : Fin (g u).order) (v : Fin n) (y : Fin (g v).order) : Bool :=
  if h : u = v then
    (g u).graph.adj x (h ▸ y)
  else
    B.graph.adj u v &&
      (x == (g u).port (perm u (B.edgePort u v))) &&
      (y == (g v).port (perm v (B.edgePort v u)))

/-- The 3-port vertex-replacement lift of cubic base `B` using per-vertex gadgets `g`
    and bijective port permutations `perm : Fin n → Fin 3 → Fin 3`. -/
def liftGraph {n : Nat} (B : CubicBase n) (g : Fin n → Gadget3)
    (perm : Fin n → Fin 3 → Fin 3) : FinGraph (liftOrder g) where
  adj a b :=
    let da := decode (fun v => (g v).order) a
    let db := decode (fun v => (g v).order) b
    liftAdjCoord B g perm da.1 da.2 db.1 db.2
  symm a b := by
    dsimp only
    generalize decode (fun v => (g v).order) a = da
    generalize decode (fun v => (g v).order) b = db
    rcases da with ⟨u, x⟩
    rcases db with ⟨v, y⟩
    simp only [liftAdjCoord]
    by_cases h : u = v
    · subst h
      simp only [↓reduceDIte]
      exact (g u).graph.symm x y
    · have h' : v ≠ u := fun heq => h heq.symm
      simp only [h, h', ↓reduceDIte]
      rw [B.graph.symm u v]
      cases B.graph.adj v u <;> cases (x == (g u).port (perm u (B.edgePort u v))) <;>
        cases (y == (g v).port (perm v (B.edgePort v u))) <;> rfl
  loopless a := by
    dsimp only
    generalize decode (fun v => (g v).order) a = da
    rcases da with ⟨u, x⟩
    simp only [liftAdjCoord, ↓reduceDIte]
    exact (g u).graph.loopless x

theorem liftGraph_adj_eq {n : Nat} (B : CubicBase n) (g : Fin n → Gadget3)
    (perm : Fin n → Fin 3 → Fin 3)
    (u : Fin n) (x : Fin (g u).order) (v : Fin n) (y : Fin (g v).order) :
    (liftGraph B g perm).adj (encode u x) (encode v y) = liftAdjCoord B g perm u x v y := by
  simp only [liftGraph]
  rw [decode_encode, decode_encode]

private theorem nodup_length_le_of_subset {α : Type} [DecidableEq α] :
    ∀ (xs ys : List α), xs.Nodup → (∀ z, z ∈ xs → z ∈ ys) → xs.length ≤ ys.length
  | [], _, _, _ => Nat.zero_le _
  | x :: xs, ys, hnd, hsub => by
    have hmem : x ∈ ys := hsub x (List.mem_cons_self ..)
    have hnd_xs : xs.Nodup := (List.nodup_cons.mp hnd).2
    have hx_not : x ∉ xs := (List.nodup_cons.mp hnd).1
    have hsub' : ∀ z, z ∈ xs → z ∈ ys.erase x := by
      intro z hz
      have hne : z ≠ x := fun h => hx_not (h ▸ hz)
      exact (List.mem_erase_of_ne hne).mpr (hsub z (List.mem_cons_of_mem x hz))
    have ih := nodup_length_le_of_subset xs (ys.erase x) hnd_xs hsub'
    have herase : (ys.erase x).length + 1 = ys.length := by
      have := List.length_erase_of_mem hmem
      have hpos : 0 < ys.length := List.length_pos_of_mem hmem
      omega
    simp only [List.length_cons]
    omega

private theorem length_filter_eq_of_nodup_iff {N : Nat} (P : Fin N → Bool) (ws : List (Fin N))
    (hnd : ws.Nodup) (hiff : ∀ z : Fin N, z ∈ ws ↔ P z = true) :
    ((List.finRange N).filter P).length = ws.length := by
  have hnd1 : ((List.finRange N).filter P).Nodup := (List.nodup_finRange N).filter P
  have hsub1 : ∀ z, z ∈ (List.finRange N).filter P → z ∈ ws := fun z hz =>
    (hiff z).mpr (List.mem_filter.mp hz).2
  have hsub2 : ∀ z, z ∈ ws → z ∈ (List.finRange N).filter P := fun z hz =>
    List.mem_filter.mpr ⟨List.mem_finRange z, (hiff z).mp hz⟩
  have hle1 := nodup_length_le_of_subset _ _ hnd1 hsub1
  have hle2 := nodup_length_le_of_subset _ _ hnd hsub2
  omega

/-- Every permutation `p : Fin 3 → Fin 3` that is injective is also surjective. -/
theorem fin3_surj_of_inj (p : Fin 3 → Fin 3) (hinj : ∀ a b : Fin 3, p a = p b → a = b) :
    ∀ b : Fin 3, ∃ a : Fin 3, p a = b := by
  intro b
  have h01 : p 0 ≠ p 1 := fun h => by have := hinj 0 1 h; simp at this
  have h02 : p 0 ≠ p 2 := fun h => by have := hinj 0 2 h; simp at this
  have h12 : p 1 ≠ p 2 := fun h => by have := hinj 1 2 h; simp at this
  have : (p 0).val ≠ (p 1).val := fun h => h01 (Fin.ext h)
  have : (p 0).val ≠ (p 2).val := fun h => h02 (Fin.ext h)
  have : (p 1).val ≠ (p 2).val := fun h => h12 (Fin.ext h)
  by_cases c0 : p 0 = b
  · exact ⟨0, c0⟩
  · by_cases c1 : p 1 = b
    · exact ⟨1, c1⟩
    · refine ⟨2, Fin.ext ?_⟩
      have : (p 0).val ≠ b.val := fun h => c0 (Fin.ext h)
      have : (p 1).val ≠ b.val := fun h => c1 (Fin.ext h)
      omega

/-- Exact degree formula for every vertex `z = encode u x` in `liftGraph`. -/
theorem liftGraph_deg_cases {n : Nat} (B : CubicBase n) (g : Fin n → Gadget3)
    (perm : Fin n → Fin 3 → Fin 3)
    (hperm : ∀ u : Fin n, ∀ a b : Fin 3, perm u a = perm u b → a = b)
    (u : Fin n) (x : Fin (g u).order) :
    ((g u).isUnit = true → (liftGraph B g perm).deg (encode u x) = 3) ∧
    ((g u).isUnit = false →
      (∃ a : Fin 3, x = (g u).port a) → (liftGraph B g perm).deg (encode u x) = 3) ∧
    ((g u).isUnit = false →
      (∀ a : Fin 3, x ≠ (g u).port a) → (liftGraph B g perm).deg (encode u x) = (g u).graph.deg x) := by
  let G := liftGraph B g perm
  let f : Fin n → Nat := fun v => (g v).order
  -- Helper: external neighbor of `u` along base-port `k : Fin 3`
  let extNbr (k : Fin 3) : Fin (liftOrder g) :=
    let v := B.nbr u k
    encode v ((g v).port (perm v (B.edgePort v u)))
  have hext_ne_u : ∀ k : Fin 3, B.nbr u k ≠ u := by
    intro k heq
    have hadj : B.graph.adj u (B.nbr u k) = true := (B.nbr_adj u _).mpr ⟨k, rfl⟩
    rw [heq, B.graph.loopless] at hadj
    exact Bool.false_ne_true hadj
  refine ⟨?_, ?_, ?_⟩
  · -- Case 1: unit vertex `U_1` (`order = 1`) -> exact 3 external neighbors `extNbr 0, 1, 2`
    intro hunit
    have hord1 : (g u).order = 1 := (g u).unit_order hunit
    have hws_nd : [extNbr 0, extNbr 1, extNbr 2].Nodup := by
      have hne : ∀ a b : Fin 3, a ≠ b → extNbr a ≠ extNbr b := by
        intro a b hab heq
        have h1 := (encode_inj heq).1
        exact hab (B.nbr_inj u a b h1)
      simp [List.nodup_cons, hne 0 1 (by decide), hne 0 2 (by decide), hne 1 2 (by decide)]
    have hiff : ∀ z : Fin (liftOrder g), z ∈ [extNbr 0, extNbr 1, extNbr 2] ↔ G.adj (encode u x) z = true := by
      intro z
      rw [← encode_decode f z]
      generalize decode f z = dz
      rcases dz with ⟨v, y⟩
      rw [liftGraph_adj_eq]
      simp only [liftAdjCoord]
      constructor
      · intro hmem
        simp at hmem
        have hk : ∃ k : Fin 3, encode v y = extNbr k := by
          rcases hmem with h | h | h
          · exact ⟨0, h⟩
          · exact ⟨1, h⟩
          · exact ⟨2, h⟩
        obtain ⟨k, hk⟩ := hk
        have hv : v = B.nbr u k := (encode_inj hk).1
        have hne : u ≠ v := fun h => hext_ne_u k (hv.symm.trans h.symm)
        simp only [hne, ↓reduceDIte, Bool.and_eq_true, beq_iff_eq]
        have hadj : B.graph.adj u v = true := by rw [hv]; exact (B.nbr_adj u _).mpr ⟨k, rfl⟩
        have hx : x = (g u).port (perm u (B.edgePort u v)) := Fin.ext (by omega)
        have hy : y = (g v).port (perm v (B.edgePort v u)) := by
          have hyval := (encode_inj hk).2
          subst hv
          exact Fin.ext hyval
        exact ⟨⟨hadj, hx⟩, hy⟩
      · intro hadj
        by_cases huv : u = v
        · subst huv
          simp only [↓reduceDIte] at hadj
          have hxy : x = y := Fin.ext (by omega)
          rw [hxy, (g u).graph.loopless] at hadj
          exact absurd hadj Bool.false_ne_true
        · simp only [huv, ↓reduceDIte, Bool.and_eq_true, beq_iff_eq] at hadj
          obtain ⟨⟨hB, _⟩, hy⟩ := hadj
          obtain ⟨k, hk⟩ := (B.nbr_adj u v).mp hB
          have hzeq : encode v y = extNbr k := by
            subst hk
            simp only [extNbr]
            rw [hy]
          have hk3 : k = 0 ∨ k = 1 ∨ k = 2 := by
            have : k.val = 0 ∨ k.val = 1 ∨ k.val = 2 := by omega
            rcases this with h | h | h
            · left; exact Fin.ext h
            · right; left; exact Fin.ext h
            · right; right; exact Fin.ext h
          rcases hk3 with rfl | rfl | rfl <;> simp [hzeq]
    change ((List.finRange (liftOrder g)).filter (G.adj (encode u x))).length = 3
    rw [length_filter_eq_of_nodup_iff _ [extNbr 0, extNbr 1, extNbr 2] hws_nd hiff]
    rfl
  · -- Case 2: non-unit port `x = port a` -> 2 internal neighbors + 1 external neighbor = 3
    intro hnu ⟨a, ha⟩
    obtain ⟨k, hk⟩ := fin3_surj_of_inj (perm u) (hperm u) a
    let intNbrs : List (Fin (liftOrder g)) := ((g u).graph.neighbors x).map (encode u)
    let ws : List (Fin (liftOrder g)) := extNbr k :: intNbrs
    have hnd_int : intNbrs.Nodup :=
      nodup_map_of_inj (fun _ _ heq => Fin.ext (encode_inj heq).2) ((List.nodup_finRange _).filter _)
    have hnotmem : extNbr k ∉ intNbrs := by
      intro hm
      change extNbr k ∈ ((g u).graph.neighbors x).map (encode u) at hm
      rw [List.mem_map] at hm
      obtain ⟨y, _, hy⟩ := hm
      have hv := (encode_inj hy).1
      exact hext_ne_u k hv.symm
    have hws_nd : ws.Nodup := List.nodup_cons.mpr ⟨hnotmem, hnd_int⟩
    have hiff : ∀ z : Fin (liftOrder g), z ∈ ws ↔ G.adj (encode u x) z = true := by
      intro z
      rw [← encode_decode f z]
      generalize decode f z = dz
      rcases dz with ⟨v, y⟩
      rw [liftGraph_adj_eq]
      dsimp only [ws, intNbrs]
      rw [List.mem_cons, List.mem_map]
      simp only [liftAdjCoord]
      constructor
      · intro hm
        rcases hm with hext | ⟨y', hy'm, hy'eq⟩
        · have hv : v = B.nbr u k := (encode_inj hext).1
          have hne : u ≠ v := fun h => hext_ne_u k (hv.symm.trans h.symm)
          simp only [hne, ↓reduceDIte, Bool.and_eq_true, beq_iff_eq]
          have hB : B.graph.adj u v = true := by rw [hv]; exact (B.nbr_adj u _).mpr ⟨k, rfl⟩
          have hep : B.edgePort u v = k := by rw [hv]; exact B.edgePort_nbr u k
          have hx : x = (g u).port (perm u (B.edgePort u v)) := by rw [ha, hep, hk]
          have hy : y = (g v).port (perm v (B.edgePort v u)) := by
            have hyval := (encode_inj hext).2
            subst hv; exact Fin.ext hyval
          exact ⟨⟨hB, hx⟩, hy⟩
        · have hv : u = v := (encode_inj hy'eq).1
          subst hv
          have hy : y' = y := Fin.ext (encode_inj hy'eq).2
          subst hy
          simp only [↓reduceDIte]
          exact (mem_neighbors_iff (g u).graph x y').mp hy'm
      · intro hadj
        by_cases huv : u = v
        · subst huv
          simp only [↓reduceDIte] at hadj
          right
          exact ⟨y, (mem_neighbors_iff (g u).graph x y).mpr hadj, rfl⟩
        · simp only [huv, ↓reduceDIte, Bool.and_eq_true, beq_iff_eq] at hadj
          obtain ⟨⟨hB, hx⟩, hy⟩ := hadj
          rw [ha] at hx
          have hp : a = perm u (B.edgePort u v) := (g u).port_inj hnu _ _ hx
          have hkp : k = B.edgePort u v := hperm u _ _ (hk.trans hp)
          have hv : B.nbr u k = v := by rw [hkp]; exact B.nbr_edgePort hB
          left
          subst hv
          simp only [extNbr]
          rw [hy]
    change ((List.finRange (liftOrder g)).filter (G.adj (encode u x))).length = 3
    rw [length_filter_eq_of_nodup_iff _ ws hws_nd hiff]
    simp only [ws, intNbrs, List.length_cons, List.length_map]
    have hdeg2 : ((g u).graph.neighbors x).length = 2 := by
      rw [ha]; exact ((g u).deg_ok hnu).1 a
    omega
  · -- Case 3: non-unit non-port vertex -> exact internal neighbors only
    intro hnu hnp
    let ws : List (Fin (liftOrder g)) := ((g u).graph.neighbors x).map (encode u)
    have hws_nd : ws.Nodup :=
      nodup_map_of_inj (fun _ _ heq => Fin.ext (encode_inj heq).2) ((List.nodup_finRange _).filter _)
    have hiff : ∀ z : Fin (liftOrder g), z ∈ ws ↔ G.adj (encode u x) z = true := by
      intro z
      rw [← encode_decode f z]
      generalize decode f z = dz
      rcases dz with ⟨v, y⟩
      rw [liftGraph_adj_eq]
      dsimp only [ws]
      rw [List.mem_map]
      simp only [liftAdjCoord]
      constructor
      · rintro ⟨y', hy'm, hy'eq⟩
        have hv : u = v := (encode_inj hy'eq).1
        subst hv
        have hy : y' = y := Fin.ext (encode_inj hy'eq).2
        subst hy
        simp only [↓reduceDIte]
        exact (mem_neighbors_iff (g u).graph x y').mp hy'm
      · intro hadj
        by_cases huv : u = v
        · subst huv
          simp only [↓reduceDIte] at hadj
          exact ⟨y, (mem_neighbors_iff (g u).graph x y).mpr hadj, rfl⟩
        · simp only [huv, ↓reduceDIte, Bool.and_eq_true, beq_iff_eq] at hadj
          exact absurd hadj.1.2 (hnp (perm u (B.edgePort u v)))
    change ((List.finRange (liftOrder g)).filter (G.adj (encode u x))).length = (g u).graph.deg x
    rw [length_filter_eq_of_nodup_iff _ ws hws_nd hiff]
    simp [ws, FinGraph.deg]

/-- **Theorem 1a (`liftGraph_minDeg3`)**: Every 3-port lift of a cubic base has `δ ≥ 3`. -/
theorem liftGraph_minDeg3 {n : Nat} (B : CubicBase n) (g : Fin n → Gadget3)
    (perm : Fin n → Fin 3 → Fin 3)
    (hperm : ∀ u : Fin n, ∀ a b : Fin 3, perm u a = perm u b → a = b) :
    (liftGraph B g perm).MinDegAtLeast 3 := by
  intro z
  rw [← encode_decode (fun v => (g v).order) z]
  generalize decode (fun v => (g v).order) z = dz
  rcases dz with ⟨u, x⟩
  obtain ⟨h1, h2, h3⟩ := liftGraph_deg_cases B g perm hperm u x
  cases hu : (g u).isUnit
  · by_cases hp : ∃ a : Fin 3, x = (g u).port a
    · rw [h2 hu hp]; exact Nat.le_refl 3
    · have hnp : ∀ a : Fin 3, x ≠ (g u).port a := fun a h => hp ⟨a, h⟩
      rw [h3 hu hnp]
      exact ((g u).deg_ok hu).2 x hnp
  · rw [h1 hu]; exact Nat.le_refl 3

/-- **Theorem 1b (`liftGraph_isCubic`)**: If every gadget is cubic-internal, the lifted graph is 3-regular. -/
theorem liftGraph_isCubic {n : Nat} (B : CubicBase n) (g : Fin n → Gadget3)
    (perm : Fin n → Fin 3 → Fin 3)
    (hperm : ∀ u : Fin n, ∀ a b : Fin 3, perm u a = perm u b → a = b)
    (hcubic : ∀ u : Fin n, (g u).IsCubicInternal) :
    (liftGraph B g perm).IsCubic := by
  intro z
  rw [← encode_decode (fun v => (g v).order) z]
  generalize decode (fun v => (g v).order) z = dz
  rcases dz with ⟨u, x⟩
  obtain ⟨h1, h2, h3⟩ := liftGraph_deg_cases B g perm hperm u x
  cases hu : (g u).isUnit
  · by_cases hp : ∃ a : Fin 3, x = (g u).port a
    · exact h2 hu hp
    · have hnp : ∀ a : Fin 3, x ≠ (g u).port a := fun a h => hp ⟨a, h⟩
      rw [h3 hu hnp]
      rcases hcubic u with htr | hdeg3
      · rw [hu] at htr; exact absurd htr Bool.false_ne_true
      · exact hdeg3 x hnp
  · exact h1 hu

/-! ### 4. The Master 3-Port Cycle Projection & Length Lower Bound Theorem -/

/-- The gadget-lift lower-bound weight function on a base triple `(prev, cur, nxt)`. -/
def liftWeight {n : Nat} (B : CubicBase n) (g : Fin n → Gadget3)
    (perm : Fin n → Fin 3 → Fin 3) (prev cur nxt : Fin n) : Nat :=
  (g cur).distLower (perm cur (B.edgePort cur prev)) (perm cur (B.edgePort cur nxt))

/-- Extract the base-vertex run start indices `0 = s_0 < s_1 < ... < s_{k-1} < L`
    for a cycle rotated so that `baseOf (L - 1) ≠ baseOf 0`. -/
private def runStarts {n L : Nat} (baseOf : Fin L → Fin n) : List (Fin L) :=
  (List.finRange L).filter fun i =>
    if h0 : i.val = 0 then true
    else decide (baseOf ⟨i.val - 1, by omega⟩ ≠ baseOf i)

private theorem runStarts_sorted {n L : Nat} (baseOf : Fin L → Fin n) :
    ∀ (a b : Nat) (ha : a < (runStarts baseOf).length) (hb : b < (runStarts baseOf).length),
      a < b → ((runStarts baseOf)[a]'ha).val < ((runStarts baseOf)[b]'hb).val := by
  -- Every sublist of `List.finRange L` is strictly increasing!
  have hsub : (runStarts baseOf).Sublist (List.finRange L) := List.filter_sublist
  have hpair : (List.finRange L).Pairwise (fun x y : Fin L => x.val < y.val) := by
    rw [List.pairwise_iff_getElem]
    intro i j hi hj hij
    simp [hij]
  have hp2 := hpair.sublist hsub
  rw [List.pairwise_iff_getElem] at hp2
  exact hp2

private theorem runStarts_head {n L : Nat} (hL : 0 < L) (baseOf : Fin L → Fin n) :
    ∃ hpos : 0 < (runStarts baseOf).length, (runStarts baseOf)[0]'hpos = ⟨0, hL⟩ := by
  have hmem : (⟨0, hL⟩ : Fin L) ∈ runStarts baseOf := by
    simp [runStarts, List.mem_filter, List.mem_finRange]
  have hpos : 0 < (runStarts baseOf).length := List.length_pos_of_mem hmem
  refine ⟨hpos, ?_⟩
  obtain ⟨idx, hidx, heq⟩ := List.getElem_of_mem hmem
  by_cases h0 : idx = 0
  · subst h0; exact heq
  · have hlt := runStarts_sorted baseOf 0 idx hpos hidx (by omega)
    rw [heq] at hlt
    simp at hlt

/-- Helper: extract internal gadget adjacency from `liftAdjCoord` when both endpoints share base `w`. -/
private theorem liftAdjCoord_same_of_eq {n : Nat} (B : CubicBase n) (g : Fin n → Gadget3)
    (perm : Fin n → Fin 3 → Fin 3) {u v w : Fin n} (h1 : u = w) (h2 : v = w)
    (x : Fin (g u).order) (y : Fin (g v).order)
    (hadj : liftAdjCoord B g perm u x v y = true) :
    (g w).graph.adj (castFin (congrArg (fun t => (g t).order) h1) x)
                    (castFin (congrArg (fun t => (g t).order) h2) y) = true := by
  subst h1; subst h2
  simp only [liftAdjCoord, ↓reduceDIte] at hadj
  exact hadj

/-- **THE MASTER 3-PORT GADGET-LIFT CYCLE DICHOTOMY (`liftGraph_cycle_dichotomy`)**:
    Every simple cycle of length `L` in `liftGraph B g perm` EITHER:
      (1) lies completely inside a single gadget `g v` (`HasCycle (g v).graph L ∧ L ≤ (g v).order`), OR
      (2) projects onto a simple cycle `C` of length `k ≥ 3` in the base graph `B` satisfying
          `k + cycleWeightSum C (liftWeight B g perm) ≤ L`. -/
theorem liftGraph_cycle_dichotomy {n : Nat} (B : CubicBase n) (g : Fin n → Gadget3)
    (perm : Fin n → Fin 3 → Fin 3)
    (hperm : ∀ u : Fin n, ∀ a b : Fin 3, perm u a = perm u b → a = b)
    {L : Nat} (c : SimpleCycle (liftGraph B g perm) L) :
    (∃ v : Fin n, (g v).graph.HasCycle L ∧ L ≤ (g v).order) ∨
    (∃ (k : Nat) (C : SimpleCycle B.graph k),
      k + cycleWeightSum C (liftWeight B g perm) ≤ L) := by
  let f : Fin n → Nat := fun v => (g v).order
  have hL := c.hlen
  -- Base projection of cycle `c`
  let base0 (i : Fin L) : Fin n := (decode f (c.vert i)).1
  by_cases hall_same : ∀ i : Fin L, base0 i = base0 ⟨0, by omega⟩
  · -- CASE 1: All vertices lie in a single gadget `v = base0 0`!
    left
    let v := base0 ⟨0, by omega⟩
    refine ⟨v, ⟨?_⟩, ?_⟩
    · refine {
        hlen := hL
        vert := fun i => castFin (congrArg (fun u => (g u).order) (hall_same i)) (decode f (c.vert i)).2
        inj := fun i j hij => by
          apply c.inj
          rw [← encode_decode f (c.vert i), ← encode_decode f (c.vert j)]
          exact encode_eq_of_val ((hall_same i).trans (hall_same j).symm) (congrArg Fin.val hij)
        edge := fun i =>
          liftAdjCoord_same_of_eq B g perm (hall_same i)
            (hall_same ⟨(i.val + 1) % L, Nat.mod_lt _ (by omega)⟩)
            (decode f (c.vert i)).2
            (decode f (c.vert ⟨(i.val + 1) % L, Nat.mod_lt _ (by omega)⟩)).2
            (c.edge i)
      }
    · -- Injective map `Fin L → Fin (g v).order` implies `L ≤ (g v).order`!
      let embed : Fin L → Fin (g v).order :=
        fun i => castFin (congrArg (fun u => (g u).order) (hall_same i)) (decode f (c.vert i)).2
      have hinj : ∀ i j : Fin L, embed i = embed j → i = j := by
        intro i j hij
        apply c.inj
        rw [← encode_decode f (c.vert i), ← encode_decode f (c.vert j)]
        exact encode_eq_of_val ((hall_same i).trans (hall_same j).symm) (congrArg Fin.val hij)
      have hnd : ((List.finRange L).map embed).Nodup :=
        nodup_map_of_inj hinj (List.nodup_finRange L)
      have hsub : ∀ x, x ∈ (List.finRange L).map embed → x ∈ List.finRange (g v).order :=
        fun x _ => List.mem_finRange x
      have hle := nodup_length_le_of_subset _ _ hnd hsub
      simp at hle
      exact hle
  · -- CASE 2: Cycle visits ≥ 2 distinct base gadgets!
    right
    -- Find an index `r` where `base0 r ≠ base0 (r + 1 mod L)`
    have hex_exit : ∃ r : Fin L, base0 r ≠ base0 ⟨(r.val + 1) % L, Nat.mod_lt _ (by omega)⟩ := by
      by_cases hex : ∃ r : Fin L, base0 r ≠ base0 ⟨(r.val + 1) % L, Nat.mod_lt _ (by omega)⟩
      · exact hex
      · exfalso; apply hall_same; intro i
        have hstep : ∀ (t : Nat) (ht : t < L), base0 ⟨t, ht⟩ = base0 ⟨0, by omega⟩ := by
          intro t
          induction t with
          | zero => intro _; rfl
          | succ t ih =>
            intro ht
            have hprev := ih (by omega)
            have hneq : ¬ (base0 ⟨t, by omega⟩ ≠ base0 ⟨(t + 1) % L, Nat.mod_lt _ (by omega)⟩) :=
              fun h => hex ⟨⟨t, by omega⟩, h⟩
            have heq : base0 ⟨t, by omega⟩ = base0 ⟨(t + 1) % L, Nat.mod_lt _ (by omega)⟩ :=
              Classical.not_not.mp hneq
            have hfin : (⟨(t + 1) % L, Nat.mod_lt _ (by omega)⟩ : Fin L) = ⟨t + 1, ht⟩ :=
              Fin.ext (Nat.mod_eq_of_lt ht)
            rw [hfin] at heq
            exact heq.symm.trans hprev
        exact hstep i.val i.isLt
    obtain ⟨r0, hr0⟩ := hex_exit
    -- Rotate `c` so that `L - 1` is an exit step (`base (L - 1) ≠ base 0`)!
    let c' := c.rotate ((r0.val + 1) % L)
    let base (i : Fin L) : Fin n := (decode f (c'.vert i)).1
    let locVal (i : Fin L) : Nat := (decode f (c'.vert i)).2.val
    have hwrap : base ⟨L - 1, by omega⟩ ≠ base ⟨0, by omega⟩ := by
      have h1 : c'.vert ⟨L - 1, by omega⟩ = c.vert r0 := by
        simp only [c', SimpleCycle.rotate]
        congr 1; apply Fin.ext
        change (L - 1 + (r0.val + 1) % L) % L = r0.val
        rw [Nat.add_mod_mod, show L - 1 + (r0.val + 1) = r0.val + L by omega,
            Nat.add_mod_right, Nat.mod_eq_of_lt r0.isLt]
      have h2 : c'.vert ⟨0, by omega⟩ = c.vert ⟨(r0.val + 1) % L, Nat.mod_lt _ (by omega)⟩ := by
        simp only [c', SimpleCycle.rotate]
        congr 1; apply Fin.ext
        change (0 + (r0.val + 1) % L) % L = (r0.val + 1) % L
        rw [Nat.zero_add, Nat.mod_mod]
      change (decode f (c'.vert ⟨L - 1, by omega⟩)).1 ≠ (decode f (c'.vert ⟨0, by omega⟩)).1
      rw [h1, h2]
      exact hr0
    -- Build the sorted list of run-start indices `S = runStarts base`
    let S := runStarts base
    let k := S.length
    obtain ⟨hk_pos, hS0⟩ := runStarts_head (by omega : 0 < L) base
    -- End index (inclusive) of run `m : Fin k`: either `S[m+1] - 1` or `L - 1`
    let runA (m : Fin k) : Fin L := S[m.val]'m.isLt
    let runEndVal (m : Fin k) : Nat :=
      if hm : m.val + 1 < k then (S[m.val + 1]'hm).val - 1 else L - 1
    have hrunEnd_lt : ∀ m : Fin k, runEndVal m < L := by
      intro m; simp only [runEndVal]
      split
      · rename_i hm; have := (S[m.val + 1]'hm).isLt; omega
      · omega
    let runB (m : Fin k) : Fin L := ⟨runEndVal m, hrunEnd_lt m⟩
    have hA_le_B : ∀ m : Fin k, (runA m).val ≤ (runB m).val := by
      intro m
      change (S[m.val]'m.isLt).val ≤ runEndVal m
      simp only [runEndVal]
      split
      · rename_i hm
        have hlt := runStarts_sorted base m.val (m.val + 1) m.isLt hm (by omega)
        change (S[m.val]'m.isLt).val < (S[m.val + 1]'hm).val at hlt
        omega
      · have := (S[m.val]'m.isLt).isLt; omega
    -- Next-run boundary identity: `(runB m + 1) % L = runA ((m + 1) % k)`!
    have hB_next : ∀ m : Fin k,
        (⟨((runB m).val + 1) % L, Nat.mod_lt _ (by omega)⟩ : Fin L) =
        runA ⟨(m.val + 1) % k, Nat.mod_lt _ hk_pos⟩ := by
      intro m
      apply Fin.ext
      change (runEndVal m + 1) % L = (S[(m.val + 1) % k]'(Nat.mod_lt _ hk_pos)).val
      simp only [runEndVal]
      by_cases hm : m.val + 1 < k
      · simp only [hm, ↓reduceDIte]
        have hlt := runStarts_sorted base m.val (m.val + 1) m.isLt hm (by omega)
        change (S[m.val]'m.isLt).val < (S[m.val + 1]'hm).val at hlt
        have hltL := (S[m.val + 1]'hm).isLt
        have hidx : (S[(m.val + 1) % k]'(Nat.mod_lt _ hk_pos)).val = (S[m.val + 1]'hm).val := by
          congr 2; exact Nat.mod_eq_of_lt hm
        rw [hidx, show (S[m.val + 1]'hm).val - 1 + 1 = (S[m.val + 1]'hm).val by omega,
            Nat.mod_eq_of_lt hltL]
      · have hmeq : m.val + 1 = k := by omega
        simp only [hm, ↓reduceDIte]
        have hidx : (S[(m.val + 1) % k]'(Nat.mod_lt _ hk_pos)).val = (S[0]'hk_pos).val := by
          congr 2; rw [hmeq, Nat.mod_self]
        rw [hidx, hS0]
        change (L - 1 + 1) % L = 0
        rw [show L - 1 + 1 = L by omega, Nat.mod_self]
    -- Previous-run boundary identity: `(runA m + L - 1) % L = runB ((m + k - 1) % k)`!
    have hA_prev : ∀ m : Fin k,
        (⟨((runA m).val + L - 1) % L, Nat.mod_lt _ (by omega)⟩ : Fin L) =
        runB ⟨(m.val + k - 1) % k, Nat.mod_lt _ hk_pos⟩ := by
      intro m
      let pm : Fin k := ⟨(m.val + k - 1) % k, Nat.mod_lt _ hk_pos⟩
      have hnext := hB_next pm
      have hpm_next : (pm.val + 1) % k = m.val := by
        simp only [pm]
        rw [Nat.mod_add_mod, show m.val + k - 1 + 1 = m.val + k by omega,
            Nat.add_mod_right, Nat.mod_eq_of_lt m.isLt]
      have heqA : runA ⟨(pm.val + 1) % k, Nat.mod_lt _ hk_pos⟩ = runA m := by
        congr 1; exact Fin.ext hpm_next
      rw [heqA] at hnext
      have hval : ((runB pm).val + 1) % L = (runA m).val := congrArg Fin.val hnext
      apply Fin.ext
      change ((runA m).val + L - 1) % L = (runB pm).val
      rw [← hval]
      by_cases hlt : (runB pm).val + 1 < L
      · rw [Nat.mod_eq_of_lt hlt, show (runB pm).val + 1 + L - 1 = (runB pm).val + L by omega,
            Nat.add_mod_right, Nat.mod_eq_of_lt (runB pm).isLt]
      · have hbe : (runB pm).val = L - 1 := by have := (runB pm).isLt; omega
        rw [hbe, show L - 1 + 1 = L by omega, Nat.mod_self,
            show 0 + L - 1 = L - 1 by omega, Nat.mod_eq_of_lt (by omega)]
    -- Within run `m`, `base t = base (runA m)` for all `runA m ≤ t ≤ runB m`!
    have hconst_run : ∀ (m : Fin k) (t : Fin L),
        (runA m).val ≤ t.val → t.val ≤ (runB m).val → base t = base (runA m) := by
      intro m t hlo hhi
      suffices ∀ (d : Nat) (hd : (runA m).val + d ≤ (runB m).val),
          base ⟨(runA m).val + d, by have := (runB m).isLt; omega⟩ = base (runA m) by
        have h := this (t.val - (runA m).val) (by omega)
        have ht : (⟨(runA m).val + (t.val - (runA m).val), by have := (runB m).isLt; omega⟩ : Fin L) = t := by
          apply Fin.ext; change (runA m).val + (t.val - (runA m).val) = t.val; omega
        rw [ht] at h; exact h
      intro d
      induction d with
      | zero =>
        intro _; congr 1
      | succ d ih =>
        intro hd
        have hprev := ih (by omega)
        let idx : Fin L := ⟨(runA m).val + d + 1, by have := (runB m).isLt; omega⟩
        have hnot_in_S : idx ∉ S := by
          intro hmem
          obtain ⟨j, hj, hSj⟩ := List.getElem_of_mem hmem
          have hgt : m.val < j := by
            by_cases hle : j ≤ m.val
            · by_cases heq : j = m.val
              · subst heq
                have hval_eq : (S[m.val]'m.isLt).val = (runA m).val := rfl
                rw [hSj] at hval_eq
                change (runA m).val + d + 1 = (runA m).val at hval_eq
                omega
              · have hlt := runStarts_sorted base j m.val hj m.isLt (by omega)
                change (S[j]'hj).val < (S[m.val]'m.isLt).val at hlt
                rw [hSj] at hlt
                change (runA m).val + d + 1 < (runA m).val at hlt
                omega
            · omega
          have hm1 : m.val + 1 < k := by omega
          have hle_next : (S[m.val + 1]'hm1).val ≤ (S[j]'hj).val := by
            by_cases heq : m.val + 1 = j
            · subst heq; exact Nat.le_refl _
            · exact Nat.le_of_lt (runStarts_sorted base (m.val + 1) j hm1 hj (by omega))
          rw [hSj] at hle_next
          have hd' : (runA m).val + (d + 1) ≤ (S[m.val + 1]'hm1).val - 1 := by
            simpa [runB, runEndVal, hm1] using hd
          change (S[m.val + 1]'hm1).val ≤ (runA m).val + d + 1 at hle_next
          omega
        have hstep_eq : base ⟨idx.val - 1, by omega⟩ = base idx := by
          by_cases hneq : base ⟨idx.val - 1, by omega⟩ ≠ base idx
          · exfalso; apply hnot_in_S
            simp only [S, runStarts, List.mem_filter, List.mem_finRange, true_and]
            have hnz : idx.val ≠ 0 := by change (runA m).val + d + 1 ≠ 0; omega
            simp [hnz, hneq]
          · exact Classical.not_not.mp hneq
        have hidx1 : (⟨idx.val - 1, by omega⟩ : Fin L) = ⟨(runA m).val + d, by have := (runB m).isLt; omega⟩ := by
          apply Fin.ext; change (runA m).val + d + 1 - 1 = (runA m).val + d; omega
        rw [hidx1] at hstep_eq
        exact hstep_eq.symm.trans hprev
    -- Between consecutive runs `m` and `m+1`, the base vertex strictly changes!
    let baseVert (m : Fin k) : Fin n := base (runA m)
    have hrun_diff : ∀ m : Fin k,
        baseVert m ≠ baseVert ⟨(m.val + 1) % k, Nat.mod_lt _ hk_pos⟩ := by
      intro m
      have hB_eq : base (runB m) = baseVert m := hconst_run m (runB m) (hA_le_B m) (Nat.le_refl _)
      rw [← hB_eq]
      by_cases hm : m.val + 1 < k
      · have hmem : runA ⟨(m.val + 1) % k, Nat.mod_lt _ hk_pos⟩ ∈ S := List.getElem_mem _
        simp only [S, runStarts, List.mem_filter, List.mem_finRange, true_and] at hmem
        have hnz : (runA ⟨(m.val + 1) % k, Nat.mod_lt _ hk_pos⟩).val ≠ 0 := by
          have hlt := runStarts_sorted base 0 (m.val + 1) hk_pos hm (by omega)
          change (S[0]'hk_pos).val < (S[m.val + 1]'hm).val at hlt
          rw [hS0] at hlt
          change (S[(m.val + 1) % k]'(Nat.mod_lt _ hk_pos)).val ≠ 0
          have hmod : (S[(m.val + 1) % k]'(Nat.mod_lt _ hk_pos)).val = (S[m.val + 1]'hm).val := by
            congr 2; exact Nat.mod_eq_of_lt hm
          rw [hmod]
          change 0 < (S[m.val + 1]'hm).val at hlt
          omega
        simp only [hnz, ↓reduceDIte, decide_eq_true_eq] at hmem
        have hpred : (⟨(runA ⟨(m.val + 1) % k, Nat.mod_lt _ hk_pos⟩).val - 1, by omega⟩ : Fin L) = runB m := by
          apply Fin.ext
          change (S[(m.val + 1) % k]'(Nat.mod_lt _ hk_pos)).val - 1 = runEndVal m
          simp only [runEndVal, hm, ↓reduceDIte]
          congr 3; exact Nat.mod_eq_of_lt hm
        rw [hpred] at hmem
        exact hmem
      · have hmeq : m.val + 1 = k := by omega
        have hBeq : runB m = ⟨L - 1, by omega⟩ := by
          apply Fin.ext
          change runEndVal m = L - 1
          simp only [runEndVal, hm, ↓reduceDIte]
        have hAeq : runA ⟨(m.val + 1) % k, Nat.mod_lt _ hk_pos⟩ = ⟨0, by omega⟩ := by
          change S[(m.val + 1) % k]'(Nat.mod_lt _ hk_pos) = ⟨0, by omega⟩
          have hidx : S[(m.val + 1) % k]'(Nat.mod_lt _ hk_pos) = S[0]'hk_pos := by
            congr 1; rw [hmeq, Nat.mod_self]
          rw [hidx]; exact hS0
        rw [hBeq]
        change base ⟨L - 1, by omega⟩ ≠ base (runA ⟨(m.val + 1) % k, Nat.mod_lt _ hk_pos⟩)
        rw [hAeq]
        exact hwrap
    -- Extract external-edge facts at every transition `runB m -> runA (m + 1 mod k)`!
    have htrans : ∀ m : Fin k,
        let nxt := ⟨(m.val + 1) % k, Nat.mod_lt _ hk_pos⟩
        B.graph.adj (baseVert m) (baseVert nxt) = true ∧
        locVal (runB m) =
          ((g (baseVert m)).port (perm (baseVert m) (B.edgePort (baseVert m) (baseVert nxt)))).val ∧
        locVal (runA nxt) =
          ((g (baseVert nxt)).port (perm (baseVert nxt) (B.edgePort (baseVert nxt) (baseVert m)))).val := by
      intro m
      let nxt : Fin k := ⟨(m.val + 1) % k, Nat.mod_lt _ hk_pos⟩
      have he := c'.edge (runB m)
      rw [hB_next m] at he
      simp only [liftGraph] at he
      have hB_base : base (runB m) = baseVert m := hconst_run m (runB m) (hA_le_B m) (Nat.le_refl _)
      have hdiff := hrun_diff m
      cases hd1 : decode f (c'.vert (runB m)) with
      | mk u1 x1 =>
        cases hd2 : decode f (c'.vert (runA nxt)) with
        | mk u2 x2 =>
          rw [hd1, hd2] at he
          have hu1 : u1 = baseVert m := by simpa [base, hd1] using hB_base
          have hu2 : u2 = baseVert nxt := by simp [baseVert, base, hd2]
          have hne12 : u1 ≠ u2 := by rw [hu1, hu2]; exact hdiff
          simp only [liftAdjCoord, hne12, ↓reduceDIte, Bool.and_eq_true, beq_iff_eq] at he
          obtain ⟨⟨hB, hx1⟩, hx2⟩ := he
          refine ⟨?_, ?_, ?_⟩
          · rw [← hu1, ← hu2]; exact hB
          · change (decode f (c'.vert (runB m))).2.val = _
            rw [hd1]; subst hu1; subst hu2; exact congrArg Fin.val hx1
          · change (decode f (c'.vert (runA nxt))).2.val = _
            rw [hd2]; subst hu1; subst hu2; exact congrArg Fin.val hx2
    -- Crucial fact: for every run `m`, previous base vertex ≠ next base vertex!
    have hprev_ne_next : ∀ m : Fin k,
        baseVert ⟨(m.val + k - 1) % k, Nat.mod_lt _ hk_pos⟩ ≠
        baseVert ⟨(m.val + 1) % k, Nat.mod_lt _ hk_pos⟩ := by
      intro m heq
      let pm : Fin k := ⟨(m.val + k - 1) % k, Nat.mod_lt _ hk_pos⟩
      let nm : Fin k := ⟨(m.val + 1) % k, Nat.mod_lt _ hk_pos⟩
      have hpm_next : (⟨(pm.val + 1) % k, Nat.mod_lt _ hk_pos⟩ : Fin k) = m := by
        apply Fin.ext; simp only [pm]
        rw [Nat.mod_add_mod, show m.val + k - 1 + 1 = m.val + k by omega,
            Nat.add_mod_right, Nat.mod_eq_of_lt m.isLt]
      have htr_in := htrans pm
      rw [hpm_next] at htr_in
      have htr_out := htrans m
      have hsame_ext : c'.vert (runB pm) = c'.vert (runA nm) := by
        rw [← encode_decode f (c'.vert (runB pm)), ← encode_decode f (c'.vert (runA nm))]
        have hbase_pm : base (runB pm) = baseVert pm := hconst_run pm (runB pm) (hA_le_B pm) (Nat.le_refl _)
        have hu : (decode f (c'.vert (runB pm))).1 = (decode f (c'.vert (runA nm))).1 :=
          hbase_pm.trans heq
        have hx : locVal (runB pm) = locVal (runA nm) := by
          rw [htr_in.2.1, htr_out.2.2, heq]
        exact encode_eq_of_val hu hx
      have hidx_eq : runB pm = runA nm := c'.inj _ _ hsame_ext
      have hsame_ab : c'.vert (runA m) = c'.vert (runB m) := by
        rw [← encode_decode f (c'.vert (runA m)), ← encode_decode f (c'.vert (runB m))]
        have hbase_b : base (runB m) = baseVert m := hconst_run m (runB m) (hA_le_B m) (Nat.le_refl _)
        have hu : (decode f (c'.vert (runA m))).1 = (decode f (c'.vert (runB m))).1 := hbase_b.symm
        have hx : locVal (runA m) = locVal (runB m) := by
          rw [htr_in.2.2, htr_out.2.1, heq]
        exact encode_eq_of_val hu hx
      have hab : runA m = runB m := c'.inj _ _ hsame_ab
      have h1 := hA_prev m
      have h2 := hB_next m
      rw [← hab] at h2
      have hval1 : ((runA m).val + L - 1) % L = (runB pm).val := congrArg Fin.val h1
      have hval2 : ((runA m).val + 1) % L = (runA nm).val := congrArg Fin.val h2
      rw [hidx_eq] at hval1
      have hmod_eq : ((runA m).val + L - 1) % L = ((runA m).val + 1) % L := hval1.trans hval2.symm
      have ha_lt := (runA m).isLt
      by_cases ha0 : (runA m).val = 0
      · rw [ha0, Nat.zero_add, Nat.mod_eq_of_lt (by omega), Nat.mod_eq_of_lt (by omega)] at hmod_eq
        omega
      · by_cases haL : (runA m).val + 1 < L
        · rw [show (runA m).val + L - 1 = (runA m).val - 1 + L by omega,
              Nat.add_mod_right, Nat.mod_eq_of_lt (by omega), Nat.mod_eq_of_lt haL] at hmod_eq
          omega
        · have hae : (runA m).val = L - 1 := by omega
          rw [hae, show L - 1 + L - 1 = (L - 2) + L by omega, Nat.add_mod_right,
              Nat.mod_eq_of_lt (by omega), show L - 1 + 1 = L by omega, Nat.mod_self] at hmod_eq
          omega
    -- Immediate consequence: `k ≥ 3`!
    have hk_ge3 : 3 ≤ k := by
      have hkpos : 0 < k := hk_pos
      have h0_ne := hrun_diff ⟨0, hk_pos⟩
      by_cases hk1 : k = 1
      · exfalso; apply h0_ne
        congr 1; apply Fin.ext; simp [hk1]
      · by_cases hk2 : k = 2
        · exfalso
          have hpn := hprev_ne_next ⟨0, hk_pos⟩
          apply hpn
          congr 1; apply Fin.ext; simp [hk2]
        · omega
    -- **3-PORT PIGEONHOLE**: `baseVert : Fin k → Fin n` is INJECTIVE!
    have hbaseVert_inj : ∀ m1 m2 : Fin k, baseVert m1 = baseVert m2 → m1 = m2 := by
      intro m1 m2 hveq
      by_cases hmeq : m1 = m2
      · exact hmeq
      · exfalso
        let v := baseVert m1
        cases hunit : (g v).isUnit
        · -- Non-unit 3-port gadget: 2 runs yield 4 pairwise distinct ports in `Fin 3` -> CONTRADICTION!
          have hrun_ports : ∀ (m : Fin k) (hmv : baseVert m = v),
              ∃ (pa pb : Fin 3),
                pa ≠ pb ∧
                locVal (runA m) = ((g v).port pa).val ∧
                locVal (runB m) = ((g v).port pb).val := by
            intro m hmv
            let pm : Fin k := ⟨(m.val + k - 1) % k, Nat.mod_lt _ hk_pos⟩
            let nm : Fin k := ⟨(m.val + 1) % k, Nat.mod_lt _ hk_pos⟩
            have hpm_next : (⟨(pm.val + 1) % k, Nat.mod_lt _ hk_pos⟩ : Fin k) = m := by
              apply Fin.ext; simp only [pm]
              rw [Nat.mod_add_mod, show m.val + k - 1 + 1 = m.val + k by omega,
                  Nat.add_mod_right, Nat.mod_eq_of_lt m.isLt]
            have htr_in := htrans pm
            rw [hpm_next] at htr_in
            have htr_out := htrans m
            have hadj_in : B.graph.adj (baseVert m) (baseVert pm) = true := by
              rw [B.graph.symm]; exact htr_in.1
            have hadj_out : B.graph.adj (baseVert m) (baseVert nm) = true := htr_out.1
            have hep_ne : B.edgePort (baseVert m) (baseVert pm) ≠ B.edgePort (baseVert m) (baseVert nm) :=
              B.edgePort_ne_of_ne hadj_in hadj_out (hprev_ne_next m)
            have hp_ne : perm (baseVert m) (B.edgePort (baseVert m) (baseVert pm)) ≠
                perm (baseVert m) (B.edgePort (baseVert m) (baseVert nm)) :=
              fun h => hep_ne (hperm _ _ _ h)
            refine ⟨perm (baseVert m) (B.edgePort (baseVert m) (baseVert pm)),
                    perm (baseVert m) (B.edgePort (baseVert m) (baseVert nm)),
                    hp_ne, ?_, ?_⟩
            · rw [htr_in.2.2, hmv]
            · rw [htr_out.2.1, hmv]
          obtain ⟨p1a, p1b, h1ne, h1a, h1b⟩ := hrun_ports m1 rfl
          obtain ⟨p2a, p2b, h2ne, h2a, h2b⟩ := hrun_ports m2 hveq.symm
          have hdisj : ∀ (i1 i2 : Fin L),
              (runA m1).val ≤ i1.val → i1.val ≤ (runB m1).val →
              (runA m2).val ≤ i2.val → i2.val ≤ (runB m2).val →
              i1 ≠ i2 := by
            intro i1 i2 ha1 hb1 ha2 hb2 heq
            have hv12 : i1.val = i2.val := congrArg Fin.val heq
            by_cases hlt : m1.val < m2.val
            · have hm1' : m1.val + 1 < k := by omega
              have hle_s : (S[m1.val + 1]'hm1').val ≤ (S[m2.val]'m2.isLt).val := by
                by_cases h' : m1.val + 1 = m2.val
                · exact Nat.le_of_eq (by congr 2)
                · exact Nat.le_of_lt (runStarts_sorted base (m1.val + 1) m2.val hm1' m2.isLt (by omega))
              have hpos : 0 < (S[m1.val + 1]'hm1').val := by
                have h0lt := runStarts_sorted base 0 (m1.val + 1) hk_pos hm1' (by omega)
                change (S[0]'hk_pos).val < (S[m1.val + 1]'hm1').val at h0lt
                rw [hS0] at h0lt; exact h0lt
              have hb1' : i1.val ≤ (S[m1.val + 1]'hm1').val - 1 := by
                simpa [runB, runEndVal, hm1'] using hb1
              have ha2' : (S[m2.val]'m2.isLt).val ≤ i2.val := ha2
              omega
            · have hlt2 : m2.val < m1.val := by
                have : m1.val ≠ m2.val := fun h => hmeq (Fin.ext h)
                omega
              have hm2' : m2.val + 1 < k := by omega
              have hle_s : (S[m2.val + 1]'hm2').val ≤ (S[m1.val]'m1.isLt).val := by
                by_cases h' : m2.val + 1 = m1.val
                · exact Nat.le_of_eq (by congr 2)
                · exact Nat.le_of_lt (runStarts_sorted base (m2.val + 1) m1.val hm2' m1.isLt (by omega))
              have hpos : 0 < (S[m2.val + 1]'hm2').val := by
                have h0lt := runStarts_sorted base 0 (m2.val + 1) hk_pos hm2' (by omega)
                change (S[0]'hk_pos).val < (S[m2.val + 1]'hm2').val at h0lt
                rw [hS0] at h0lt; exact h0lt
              have hb2' : i2.val ≤ (S[m2.val + 1]'hm2').val - 1 := by
                simpa [runB, runEndVal, hm2'] using hb2
              have ha1' : (S[m1.val]'m1.isLt).val ≤ i1.val := ha1
              omega
          have hp_distinct : ∀ (i1 i2 : Fin L) (q1 q2 : Fin 3),
              i1 ≠ i2 →
              base i1 = v → base i2 = v →
              locVal i1 = ((g v).port q1).val →
              locVal i2 = ((g v).port q2).val →
              q1 ≠ q2 := by
            intro i1 i2 q1 q2 hine hb1 hb2 hl1 hl2 hq
            apply hine
            apply c'.inj
            rw [← encode_decode f (c'.vert i1), ← encode_decode f (c'.vert i2)]
            exact encode_eq_of_val (hb1.trans hb2.symm) (by change locVal i1 = locVal i2; rw [hl1, hl2, hq])
          have h1a2a : p1a ≠ p2a := hp_distinct (runA m1) (runA m2) p1a p2a
            (hdisj _ _ (Nat.le_refl _) (hA_le_B m1) (Nat.le_refl _) (hA_le_B m2))
            rfl hveq.symm h1a h2a
          have h1a2b : p1a ≠ p2b := hp_distinct (runA m1) (runB m2) p1a p2b
            (hdisj _ _ (Nat.le_refl _) (hA_le_B m1) (hA_le_B m2) (Nat.le_refl _))
            rfl ((hconst_run m2 (runB m2) (hA_le_B m2) (Nat.le_refl _)).trans hveq.symm) h1a h2b
          have h1b2a : p1b ≠ p2a := hp_distinct (runB m1) (runA m2) p1b p2a
            (hdisj _ _ (hA_le_B m1) (Nat.le_refl _) (Nat.le_refl _) (hA_le_B m2))
            (hconst_run m1 (runB m1) (hA_le_B m1) (Nat.le_refl _)) hveq.symm h1b h2a
          have h1b2b : p1b ≠ p2b := hp_distinct (runB m1) (runB m2) p1b p2b
            (hdisj _ _ (hA_le_B m1) (Nat.le_refl _) (hA_le_B m2) (Nat.le_refl _))
            (hconst_run m1 (runB m1) (hA_le_B m1) (Nat.le_refl _))
            ((hconst_run m2 (runB m2) (hA_le_B m2) (Nat.le_refl _)).trans hveq.symm) h1b h2b
          have : p1a.val ≠ p1b.val := fun h => h1ne (Fin.ext h)
          have : p2a.val ≠ p2b.val := fun h => h2ne (Fin.ext h)
          have : p1a.val ≠ p2a.val := fun h => h1a2a (Fin.ext h)
          have : p1a.val ≠ p2b.val := fun h => h1a2b (Fin.ext h)
          have : p1b.val ≠ p2a.val := fun h => h1b2a (Fin.ext h)
          have : p1b.val ≠ p2b.val := fun h => h1b2b (Fin.ext h)
          omega
        · -- Unit gadget (`order = 1`): two runs visiting `v` collide on the single vertex `0`!
          have hord1 : (g v).order = 1 := (g v).unit_order hunit
          have heq_v : c'.vert (runA m1) = c'.vert (runA m2) := by
            rw [← encode_decode f (c'.vert (runA m1)), ← encode_decode f (c'.vert (runA m2))]
            have hu1 : (decode f (c'.vert (runA m1))).1 = v := rfl
            have hu2 : (decode f (c'.vert (runA m2))).1 = v := hveq.symm
            have hx1 : (decode f (c'.vert (runA m1))).2.val < 1 := by
              have hlt := (decode f (c'.vert (runA m1))).2.isLt
              have hord_eq : f (decode f (c'.vert (runA m1))).1 = 1 := by
                change (g (decode f (c'.vert (runA m1))).1).order = 1
                rw [hu1, hord1]
              omega
            have hx2 : (decode f (c'.vert (runA m2))).2.val < 1 := by
              have hlt := (decode f (c'.vert (runA m2))).2.isLt
              have hord_eq : f (decode f (c'.vert (runA m2))).1 = 1 := by
                change (g (decode f (c'.vert (runA m2))).1).order = 1
                rw [hu2, hord1]
              omega
            exact encode_eq_of_val (hu1.trans hu2.symm) (by omega)
          have haeq : runA m1 = runA m2 := c'.inj _ _ heq_v
          have hval_eq : (S[m1.val]'m1.isLt).val = (S[m2.val]'m2.isLt).val := congrArg Fin.val haeq
          by_cases hlt : m1.val < m2.val
          · have hlt' := runStarts_sorted base m1.val m2.val m1.isLt m2.isLt hlt
            change (S[m1.val]'m1.isLt).val < (S[m2.val]'m2.isLt).val at hlt'
            omega
          · have hlt2 : m2.val < m1.val := by
              have : m1.val ≠ m2.val := fun h => hmeq (Fin.ext h)
              omega
            have hlt' := runStarts_sorted base m2.val m1.val m2.isLt m1.isLt hlt2
            change (S[m2.val]'m2.isLt).val < (S[m1.val]'m1.isLt).val at hlt'
            omega
    -- Assemble the projected `SimpleCycle B.graph k`!
    let C : SimpleCycle B.graph k := {
      hlen := hk_ge3
      vert := baseVert
      inj := hbaseVert_inj
      edge := fun m => (htrans m).1
    }
    refine ⟨k, C, ?_⟩
    -- Prove per-run length lower bound: `liftWeight B g perm prev cur nxt ≤ runB m - runA m`!
    have hrun_lb : ∀ m : Fin k,
        liftWeight B g perm
          (C.vert ⟨(m.val + k - 1) % k, Nat.mod_lt _ hk_pos⟩)
          (C.vert m)
          (C.vert ⟨(m.val + 1) % k, Nat.mod_lt _ hk_pos⟩) ≤
        (runB m).val - (runA m).val := by
      intro m
      let pm : Fin k := ⟨(m.val + k - 1) % k, Nat.mod_lt _ hk_pos⟩
      let nm : Fin k := ⟨(m.val + 1) % k, Nat.mod_lt _ hk_pos⟩
      have hpm_next : (⟨(pm.val + 1) % k, Nat.mod_lt _ hk_pos⟩ : Fin k) = m := by
        apply Fin.ext; simp only [pm]
        rw [Nat.mod_add_mod, show m.val + k - 1 + 1 = m.val + k by omega,
            Nat.add_mod_right, Nat.mod_eq_of_lt m.isLt]
      have htr_in := htrans pm
      rw [hpm_next] at htr_in
      have htr_out := htrans m
      let d := (runB m).val - (runA m).val
      let v := baseVert m
      let pa := perm v (B.edgePort v (baseVert pm))
      let pb := perm v (B.edgePort v (baseVert nm))
      have hadj_in : B.graph.adj v (baseVert pm) = true := by rw [B.graph.symm]; exact htr_in.1
      have hadj_out : B.graph.adj v (baseVert nm) = true := htr_out.1
      have hpa_ne_pb : pa ≠ pb := fun h =>
        B.edgePort_ne_of_ne hadj_in hadj_out (hprev_ne_next m) (hperm v _ _ h)
      have hconst_i : ∀ i : Fin (d + 1), base ⟨(runA m).val + i.val, by have := (runB m).isLt; omega⟩ = v :=
        fun i => hconst_run m ⟨(runA m).val + i.val, by have := (runB m).isLt; omega⟩
          (by change (runA m).val ≤ (runA m).val + i.val; omega)
          (by change (runA m).val + i.val ≤ (runB m).val; have := i.isLt; have := hA_le_B m; omega)
      let p : SimplePath (g v).graph ((g v).port pa) ((g v).port pb) d := {
        vert := fun i =>
          castFin (congrArg (fun u => (g u).order) (hconst_i i))
            (decode f (c'.vert ⟨(runA m).val + i.val, by have := (runB m).isLt; omega⟩)).2
        start_eq := by
          apply Fin.ext
          have h0 : (⟨(runA m).val + 0, by have := (runB m).isLt; omega⟩ : Fin L) = runA m :=
            Fin.ext (by simp)
          change locVal ⟨(runA m).val + 0, _⟩ = ((g v).port pa).val
          rw [h0]
          exact htr_in.2.2
        end_eq := by
          apply Fin.ext
          have hend : (⟨(runA m).val + d, by have := (runB m).isLt; omega⟩ : Fin L) = runB m :=
            Fin.ext (by change (runA m).val + ((runB m).val - (runA m).val) = (runB m).val; have := hA_le_B m; omega)
          change locVal ⟨(runA m).val + d, _⟩ = ((g v).port pb).val
          rw [hend]
          exact htr_out.2.1
        inj := fun i j hij => by
          have hceq : c'.vert ⟨(runA m).val + i.val, by have := (runB m).isLt; omega⟩ =
              c'.vert ⟨(runA m).val + j.val, by have := (runB m).isLt; omega⟩ := by
            rw [← encode_decode f (c'.vert ⟨(runA m).val + i.val, by have := (runB m).isLt; omega⟩),
                ← encode_decode f (c'.vert ⟨(runA m).val + j.val, by have := (runB m).isLt; omega⟩)]
            exact encode_eq_of_val ((hconst_i i).trans (hconst_i j).symm) (congrArg Fin.val hij)
          have hfin := c'.inj _ _ hceq
          have hval : (runA m).val + i.val = (runA m).val + j.val := congrArg Fin.val hfin
          exact Fin.ext (by omega)
        edge := fun i => by
          have hltL : (runA m).val + i.val + 1 < L := by have := (runB m).isLt; have := i.isLt; omega
          have he := c'.edge ⟨(runA m).val + i.val, by omega⟩
          have hnext_fin : (⟨((runA m).val + i.val + 1) % L, Nat.mod_lt _ (by omega)⟩ : Fin L) =
              ⟨(runA m).val + i.val + 1, hltL⟩ := Fin.ext (Nat.mod_eq_of_lt hltL)
          rw [hnext_fin] at he
          exact liftAdjCoord_same_of_eq B g perm
            (hconst_i ⟨i.val, by omega⟩) (hconst_i ⟨i.val + 1, by omega⟩)
            (decode f (c'.vert ⟨(runA m).val + i.val, by omega⟩)).2
            (decode f (c'.vert ⟨(runA m).val + i.val + 1, hltL⟩)).2
            he
      }
      exact (g v).distLower_sound pa pb d hpa_ne_pb p
    -- Sum `1 + (runB m - runA m)` over `m : Fin k` to get `L`!
    have hsum_runs : ∀ (t : Nat) (ht : t ≤ k),
        ((List.finRange k).take t).foldl (fun acc m =>
          acc + (1 + liftWeight B g perm
            (C.vert ⟨(m.val + k - 1) % k, Nat.mod_lt _ hk_pos⟩)
            (C.vert m)
            (C.vert ⟨(m.val + 1) % k, Nat.mod_lt _ hk_pos⟩))) 0 ≤
        if ht0 : t = 0 then 0 else if htk : t < k then (S[t]'htk).val else L := by
      intro t
      induction t with
      | zero => intro _; simp
      | succ t ih =>
        intro ht
        have htk' : t < k := by omega
        have htake : (List.finRange k).take (t + 1) = (List.finRange k).take t ++ [⟨t, htk'⟩] := by
          apply List.ext_getElem
          · simp; omega
          · intro idx h1 h2
            by_cases hlt : idx < t
            · rw [List.getElem_append_left (by simp; omega)]; simp
            · have heq : idx = t := by simp at h1; omega
              subst heq
              rw [List.getElem_append_right (by simp; omega)]; simp
        rw [htake, List.foldl_append, foldl_add_shift]
        simp only [List.foldl_cons, List.foldl_nil, Nat.zero_add]
        have hih := ih (by omega)
        have hlb : liftWeight B g perm
            (C.vert ⟨(t + k - 1) % k, Nat.mod_lt _ hk_pos⟩)
            (C.vert ⟨t, htk'⟩)
            (C.vert ⟨(t + 1) % k, Nat.mod_lt _ hk_pos⟩) ≤
            (runB ⟨t, htk'⟩).val - (runA ⟨t, htk'⟩).val := hrun_lb ⟨t, htk'⟩
        have hle_ab := hA_le_B ⟨t, htk'⟩
        by_cases ht0 : t = 0
        · subst ht0
          simp only [↓reduceDIte] at hih
          simp only [show ¬(0 + 1 = 0) by omega, ↓reduceDIte, Nat.zero_add]
          simp only [Nat.zero_add] at hlb
          have hA0 : (runA ⟨0, htk'⟩).val = 0 := by
            change (S[0]'htk').val = 0; rw [hS0]
          by_cases h1k : 1 < k
          · simp only [h1k, ↓reduceDIte]
            have hB0 : (runB ⟨0, htk'⟩).val = (S[1]'h1k).val - 1 := by
              change runEndVal ⟨0, htk'⟩ = (S[1]'h1k).val - 1
              simp only [runEndVal, h1k, ↓reduceDIte]
            have hS1pos : 0 < (S[1]'h1k).val := by
              have hlt := runStarts_sorted base 0 1 htk' h1k (by omega)
              change (S[0]'htk').val < (S[1]'h1k).val at hlt
              rw [hS0] at hlt; exact hlt
            omega
          · simp only [h1k, ↓reduceDIte]
            have hB0 : (runB ⟨0, htk'⟩).val = L - 1 := by
              change runEndVal ⟨0, htk'⟩ = L - 1
              simp only [runEndVal, h1k, ↓reduceDIte]
            omega
        · simp only [ht0, htk', ↓reduceDIte] at hih
          simp only [show ¬(t + 1 = 0) by omega, ↓reduceDIte]
          have hAt : (runA ⟨t, htk'⟩).val = (S[t]'htk').val := rfl
          by_cases ht1k : t + 1 < k
          · simp only [ht1k, ↓reduceDIte]
            have hBt : (runB ⟨t, htk'⟩).val = (S[t + 1]'ht1k).val - 1 := by
              change runEndVal ⟨t, htk'⟩ = (S[t + 1]'ht1k).val - 1
              simp only [runEndVal, ht1k, ↓reduceDIte]
            have hltS := runStarts_sorted base t (t + 1) htk' ht1k (by omega)
            change (S[t]'htk').val < (S[t + 1]'ht1k).val at hltS
            omega
          · simp only [ht1k, ↓reduceDIte]
            have hBt : (runB ⟨t, htk'⟩).val = L - 1 := by
              change runEndVal ⟨t, htk'⟩ = L - 1
              simp only [runEndVal, ht1k, ↓reduceDIte]
            have hltL := (S[t]'htk').isLt
            omega
    have htot := hsum_runs k (Nat.le_refl k)
    simp only [show ¬(k = 0) by omega, show ¬(k < k) by omega, ↓reduceDIte] at htot
    rw [List.take_of_length_le (by simp)] at htot
    have hsplit_sum : ∀ (xs : List (Fin k)) (g0 : Fin k → Nat),
        xs.foldl (fun acc m => acc + (1 + g0 m)) 0 =
        xs.length + xs.foldl (fun acc m => acc + g0 m) 0 := by
      intro xs g0
      induction xs with
      | nil => simp
      | cons x xs ih =>
        simp only [List.foldl_cons, Nat.zero_add, List.length_cons]
        rw [foldl_add_shift (fun m => 1 + g0 m) xs (1 + g0 x),
            foldl_add_shift g0 xs (g0 x), ih]
        omega
    rw [hsplit_sum (List.finRange k), List.length_finRange] at htot
    exact htot

/-- **Master Cycle-Absence Corollary (`liftGraph_no_cycle`)**:
    To prove `¬ (liftGraph B g perm).HasCycle T`, it suffices that:
      1. No individual gadget `g v` has a cycle of length `T` (automatic whenever `(g v).order < T`!),
      2. Every gadget has `distLower ≥ dMin` (so every base cycle of length `k > maxBaseLen` gives `k * (1 + dMin) > T`),
      3. `B.graph.checkWeightedCycles (liftWeight B g perm) maxBaseLen (T + 1) = true`. -/
theorem liftGraph_no_cycle {n : Nat} (B : CubicBase n) (g : Fin n → Gadget3)
    (perm : Fin n → Fin 3 → Fin 3)
    (hperm : ∀ u : Fin n, ∀ a b : Fin 3, perm u a = perm u b → a = b)
    (T maxBaseLen dMin : Nat)
    (hlocal : ∀ v : Fin n, ¬ (g v).graph.HasCycle T)
    (hdmin : ∀ (prev cur nxt : Fin n),
      B.graph.adj cur prev = true → B.graph.adj cur nxt = true → prev ≠ nxt →
      dMin ≤ liftWeight B g perm prev cur nxt)
    (hlong : T < (maxBaseLen + 1) * (1 + dMin))
    (hshort : B.graph.checkWeightedCycles (liftWeight B g perm) maxBaseLen (T + 1) = true) :
    ¬ (liftGraph B g perm).HasCycle T := by
  rintro ⟨c⟩
  rcases liftGraph_cycle_dichotomy B g perm hperm c with ⟨v, hv, _⟩ | ⟨k, C, hlen⟩
  · exact hlocal v hv
  · by_cases hk : k ≤ maxBaseLen
    · have h1 := weighted_cycle_lower_of_check B.graph (liftWeight B g perm) maxBaseLen (T + 1) hshort C hk
      omega
    · -- Long base cycle: `k ≥ maxBaseLen + 1`, each vertex contributes `≥ dMin`!
      have hws : k * dMin ≤ cycleWeightSum C (liftWeight B g perm) := by
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
        have h := hfold_lb (List.finRange k)
        simpa [cycleWeightSum] using h
      have hkmul : (maxBaseLen + 1) * (1 + dMin) ≤ k * (1 + dMin) :=
        Nat.mul_le_mul_right (1 + dMin) (by omega)
      have hkd : k * (1 + dMin) = k + k * dMin := by rw [Nat.mul_add, Nat.mul_one]
      omega

/-- Automatic local cycle absence whenever `order < T`. -/
theorem not_hasCycle_of_order_lt {m T : Nat} (G : FinGraph m) (h : m < T) : ¬ G.HasCycle T := by
  rintro ⟨c⟩
  have hnd : ((List.finRange T).map c.vert).Nodup := nodup_map_of_inj c.inj (List.nodup_finRange T)
  have hle := nodup_length_le_of_subset _ _ hnd (fun x _ => List.mem_finRange x)
  simp at hle
  omega

end Sglab
