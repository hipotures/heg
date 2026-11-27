/-!
# Sglab.Graph — Self-Contained Finite Simple Graphs, Simple Paths, Simple Cycles,
  BFS Distance Potentials, and Provably Sound Bitmask DFS Checkers

Zero external dependencies (pure Lean 4 stdlib), zero `sorry`, zero custom axioms.
-/

namespace Sglab

/-- A finite simple undirected graph on `Fin n`, represented by a decidable boolean
    adjacency relation that is symmetric and irreflexive (loopless). -/
structure FinGraph (n : Nat) where
  adj : Fin n → Fin n → Bool
  symm : ∀ u v : Fin n, adj u v = adj v u
  loopless : ∀ u : Fin n, adj u u = false

namespace FinGraph

variable {n : Nat}

/-- The list of neighbors of vertex `u` in `G`. -/
def neighbors (G : FinGraph n) (u : Fin n) : List (Fin n) :=
  (List.finRange n).filter (G.adj u)

/-- The degree of vertex `u` in `G`. -/
def deg (G : FinGraph n) (u : Fin n) : Nat :=
  (G.neighbors u).length

/-- `G` is `k`-regular if every vertex has degree `k`. -/
def IsRegular (G : FinGraph n) (k : Nat) : Prop :=
  ∀ u : Fin n, G.deg u = k

/-- `G` is cubic (`3`-regular). -/
def IsCubic (G : FinGraph n) : Prop := G.IsRegular 3

/-- Every vertex of `G` has degree at least `d`. -/
def MinDegAtLeast (G : FinGraph n) (d : Nat) : Prop :=
  ∀ u : Fin n, d ≤ G.deg u

/-- A simple cycle of length `L ≥ 3` in `G`: an injective map `Fin L → Fin n`
    whose cyclic consecutive vertices are adjacent. -/
structure SimpleCycle (G : FinGraph n) (L : Nat) where
  hlen : 3 ≤ L
  vert : Fin L → Fin n
  inj : ∀ i j : Fin L, vert i = vert j → i = j
  edge : ∀ i : Fin L,
    G.adj (vert i) (vert ⟨(i.val + 1) % L, Nat.mod_lt _ (by omega)⟩) = true

/-- `G` contains a simple cycle of length `L`. -/
def HasCycle (G : FinGraph n) (L : Nat) : Prop :=
  Nonempty (SimpleCycle G L)

/-- A simple path of `d` edges (`d + 1` pairwise distinct vertices) from `s` to `t`. -/
structure SimplePath (G : FinGraph n) (s t : Fin n) (d : Nat) where
  vert : Fin (d + 1) → Fin n
  start_eq : vert ⟨0, by omega⟩ = s
  end_eq : vert ⟨d, by omega⟩ = t
  inj : ∀ i j : Fin (d + 1), vert i = vert j → i = j
  edge : ∀ i : Fin d,
    G.adj (vert ⟨i.val, by omega⟩) (vert ⟨i.val + 1, by omega⟩) = true

/-- **BFS Distance Potential Lower Bound**:
    If `φ : Fin n → Nat` satisfies `φ s = 0` and increases by at most `+1` across
    every edge of `G`, then any simple path of length `d` from `s` to `t` has `φ t ≤ d`. -/
theorem dist_lower_of_potential (G : FinGraph n) (φ : Fin n → Nat)
    (s t : Fin n) (d : Nat) (p : SimplePath G s t d)
    (h0 : φ s = 0)
    (hstep : ∀ u v : Fin n, G.adj u v = true → φ v ≤ φ u + 1) :
    φ t ≤ d := by
  have hwalk : ∀ (k : Nat) (hk : k ≤ d), φ (p.vert ⟨k, by omega⟩) ≤ k := by
    intro k
    induction k with
    | zero =>
      intro _
      rw [p.start_eq, h0]
      exact Nat.le_refl 0
    | succ k ih =>
      intro hk
      have h1 := ih (by omega)
      have hadj := p.edge ⟨k, by omega⟩
      have h2 := hstep _ _ hadj
      simp only at h2
      omega
  have hend := hwalk d (Nat.le_refl d)
  rw [p.end_eq] at hend
  exact hend

private theorem mod_add_comm_shift (i r L : Nat) :
    ((i + r) % L + 1) % L = ((i + 1) % L + r) % L := by
  rw [Nat.mod_add_mod, Nat.mod_add_mod]
  congr 1; omega

/-- Rotating a `SimpleCycle` by shift `r` yields a `SimpleCycle` of the same length. -/
def SimpleCycle.rotate {G : FinGraph n} {L : Nat} (c : SimpleCycle G L) (r : Nat) :
    SimpleCycle G L where
  hlen := c.hlen
  vert i := c.vert ⟨(i.val + r) % L, Nat.mod_lt _ (by have := c.hlen; omega)⟩
  inj i j hij := by
    have hL := c.hlen
    have h := c.inj _ _ hij
    have hv : (i.val + r) % L = (j.val + r) % L := congrArg Fin.val h
    have hi : i.val < L := i.isLt
    have hj : j.val < L := j.isLt
    have hrem : (i.val + r % L) % L = (j.val + r % L) % L := by
      rw [Nat.add_mod_mod, Nat.add_mod_mod]; exact hv
    let rm := r % L
    have hr : rm < L := Nat.mod_lt r (by omega)
    have hrem' : (i.val + rm) % L = (j.val + rm) % L := hrem
    have : i.val = j.val := by
      by_cases h1 : i.val + rm < L <;> by_cases h2 : j.val + rm < L
      · rw [Nat.mod_eq_of_lt h1, Nat.mod_eq_of_lt h2] at hrem'; omega
      · rw [Nat.mod_eq_of_lt h1, Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega)] at hrem'; omega
      · rw [Nat.mod_eq_of_lt h2, Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega)] at hrem'; omega
      · rw [Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega),
            Nat.mod_eq_sub_mod (by omega), Nat.mod_eq_of_lt (by omega)] at hrem'; omega
    exact Fin.ext this
  edge i := by
    have he := c.edge ⟨(i.val + r) % L, Nat.mod_lt _ (by have := c.hlen; omega)⟩
    have hmod : ((i.val + r) % L + 1) % L = ((i.val + 1) % L + r) % L :=
      mod_add_comm_shift i.val r L
    simp only
    simpa [hmod] using he

/-- Every `SimpleCycle` achieves a minimum vertex index at some position `i0`. -/
theorem SimpleCycle.exists_min_pos {G : FinGraph n} {L : Nat} (c : SimpleCycle G L) :
    ∃ i0 : Fin L, ∀ j : Fin L, (c.vert i0).val ≤ (c.vert j).val := by
  have hL : 0 < L := by have := c.hlen; omega
  suffices ∀ (k : Nat) (hk : k < L),
      ∃ i0 : Fin L, i0.val ≤ k ∧ ∀ j : Fin L, j.val ≤ k → (c.vert i0).val ≤ (c.vert j).val by
    obtain ⟨i0, _, hi0⟩ := this (L - 1) (by omega)
    exact ⟨i0, fun j => hi0 j (by omega)⟩
  intro k
  induction k with
  | zero =>
    intro hk
    refine ⟨⟨0, hk⟩, Nat.le_refl 0, fun j hj => ?_⟩
    have hj0 : j = ⟨0, hk⟩ := Fin.ext (by show j.val = 0; omega)
    rw [hj0]
    exact Nat.le_refl _
  | succ k ih =>
    intro hk
    obtain ⟨i0, hi0_le, hi0_min⟩ := ih (by omega)
    let ik : Fin L := ⟨k + 1, hk⟩
    by_cases hle : (c.vert i0).val ≤ (c.vert ik).val
    · refine ⟨i0, by omega, fun j hj => ?_⟩
      by_cases hj' : j.val ≤ k
      · exact hi0_min j hj'
      · have hjeq : j = ik := Fin.ext (by show j.val = k + 1; omega)
        rw [hjeq]; exact hle
    · refine ⟨ik, Nat.le_refl _, fun j hj => ?_⟩
      by_cases hj' : j.val ≤ k
      · have := hi0_min j hj'; omega
      · have hjeq : j = ik := Fin.ext (by show j.val = k + 1; omega)
        rw [hjeq]; exact Nat.le_refl _

/-- Canonical rotation: every `SimpleCycle G L` rotates to one whose vertex `0` is strictly
    smaller than all other vertices on the cycle. -/
theorem SimpleCycle.exists_canonical {G : FinGraph n} {L : Nat} (c : SimpleCycle G L) :
    ∃ c' : SimpleCycle G L, ∀ j : Fin L, j.val ≠ 0 →
      (c'.vert ⟨0, by have := c.hlen; omega⟩).val < (c'.vert j).val := by
  obtain ⟨i0, hi0⟩ := c.exists_min_pos
  let c' := c.rotate i0.val
  refine ⟨c', fun j hj => ?_⟩
  have hL := c.hlen
  have h0 : c'.vert ⟨0, by omega⟩ = c.vert i0 := by
    simp [c', SimpleCycle.rotate, Nat.mod_eq_of_lt i0.isLt]
  rw [h0]
  have hle := hi0 ⟨(j.val + i0.val) % L, Nat.mod_lt _ (by omega)⟩
  have hne : c'.vert ⟨0, by omega⟩ ≠ c'.vert j := fun heq => by
    have := c'.inj _ _ heq
    exact hj (congrArg Fin.val this).symm
  rw [h0] at hne
  have hval_ne : (c.vert i0).val ≠ (c'.vert j).val := fun h => hne (Fin.ext h)
  change (c.vert i0).val < (c.vert ⟨(j.val + i0.val) % L, _⟩).val
  change (c.vert i0).val ≠ (c.vert ⟨(j.val + i0.val) % L, _⟩).val at hval_ne
  omega

/-- Precomputed adjacency list representation for fast kernel reduction. -/
def adjArray (G : FinGraph n) : Array (List (Fin n)) :=
  Array.ofFn (fun u : Fin n => G.neighbors u)

theorem mem_neighbors_iff (G : FinGraph n) (u v : Fin n) :
    v ∈ G.neighbors u ↔ G.adj u v = true := by
  simp [neighbors, List.mem_filter, List.mem_finRange]

theorem getD_adjArray (G : FinGraph n) (u : Fin n) :
    G.adjArray.getD u.val [] = G.neighbors u := by
  simp [Array.getD, adjArray]

private theorem testBit_one_shiftLeft_ne (a b : Nat) (h : a ≠ b) :
    (1 <<< a).testBit b = false := by
  rw [Nat.testBit_shiftLeft]
  by_cases hle : a ≤ b
  · have hne0 : b - a ≠ 0 := by omega
    have h1 : (1 : Nat).testBit (b - a) = false := by
      cases hsub : b - a with
      | zero => omega
      | succ k =>
        rw [Nat.testBit, Nat.shiftRight_succ, Nat.shiftRight_eq_div_pow]
        have hle1 : 1 / 2 ^ k ≤ 1 := Nat.div_le_self 1 (2 ^ k)
        have hdiv : 1 / 2 ^ k / 2 = 0 := Nat.div_eq_of_lt (by omega)
        rw [hdiv]; rfl
    simp [hle, h1]
  · simp [hle]

/-! ### 1. Provably Sound Exact Cycle-Existence DFS (`hasCycleDfs`) -/

/-- Exact canonical-start DFS checking whether there exists a simple path of `rem` edges
    from `u` back to `s` using only vertices `w > s` not set in bitmask `vis`. -/
def hasPathBack (adj : Array (List (Fin n))) (s u : Fin n) : Nat → Nat → Bool
  | 0, _ => false
  | 1, _ => (adj.getD u.val []).contains s
  | rem + 2, vis =>
    (adj.getD u.val []).any fun w =>
      if s.val < w.val && !vis.testBit w.val then
        hasPathBack adj s w (rem + 1) (vis ||| (1 <<< w.val))
      else
        false

/-- Exact check whether `G` has ANY simple cycle of length `L ≥ 3`. -/
def hasCycleDfs (G : FinGraph n) (L : Nat) : Bool :=
  let adj := G.adjArray
  (List.finRange n).any fun s =>
    hasPathBack adj s s L (1 <<< s.val)

theorem hasPathBack_complete (G : FinGraph n) (s : Fin n) :
    ∀ (rem : Nat) (u : Fin n) (vis : Nat)
      (path : Fin (rem + 1) → Fin n),
      1 ≤ rem →
      path ⟨0, by omega⟩ = u →
      path ⟨rem, by omega⟩ = s →
      (∀ i : Fin rem, G.adj (path ⟨i.val, by omega⟩) (path ⟨i.val + 1, by omega⟩) = true) →
      (∀ i : Fin rem, 0 < i.val → s.val < (path ⟨i.val, by omega⟩).val) →
      (∀ i : Fin rem, 0 < i.val → vis.testBit (path ⟨i.val, by omega⟩).val = false) →
      (∀ i j : Fin rem, 0 < i.val → 0 < j.val → path ⟨i.val, by omega⟩ = path ⟨j.val, by omega⟩ → i = j) →
      hasPathBack G.adjArray s u rem vis = true
  | 0, _, _, _, hrem, _, _, _, _, _, _ => by omega
  | 1, u, vis, path, _, h0, h1, hedge, _, _, _ => by
    simp only [hasPathBack, getD_adjArray, List.contains_eq_mem, decide_eq_true_eq, mem_neighbors_iff]
    have he := hedge ⟨0, by omega⟩
    have ha : path ⟨0, by omega⟩ = u := h0
    have hb : path ⟨1, by omega⟩ = s := h1
    simp only at he
    rw [ha, hb] at he
    exact he
  | rem + 2, u, vis, path, _, h0, hlast, hedge, hgt, hvis, hinj => by
    simp only [hasPathBack, getD_adjArray, List.any_eq_true]
    let w := path ⟨1, by omega⟩
    refine ⟨w, ?_, ?_⟩
    · rw [mem_neighbors_iff]
      have he := hedge ⟨0, by omega⟩
      simp only at he
      rw [h0] at he
      exact he
    · have hw_gt : s.val < w.val := hgt ⟨1, by omega⟩ (by show 0 < 1; omega)
      have hw_vis : vis.testBit w.val = false := hvis ⟨1, by omega⟩ (by show 0 < 1; omega)
      have hcond : (decide (s.val < w.val) && !vis.testBit w.val) = true := by
        simp [hw_gt, hw_vis]
      simp only [hcond, ↓reduceIte]
      let path' : Fin (rem + 2) → Fin n := fun i => path ⟨i.val + 1, by omega⟩
      apply hasPathBack_complete G s (rem + 1) w (vis ||| (1 <<< w.val)) path' (by omega)
      · rfl
      · simpa [path'] using hlast
      · intro i; exact hedge ⟨i.val + 1, by omega⟩
      · intro i hi; exact hgt ⟨i.val + 1, by omega⟩ (by show 0 < i.val + 1; omega)
      · intro i hi
        have h1 := hvis ⟨i.val + 1, by omega⟩ (by show 0 < i.val + 1; omega)
        have hne : w.val ≠ (path ⟨i.val + 1, by omega⟩).val := fun heq => by
          have hfin := hinj ⟨1, by omega⟩ ⟨i.val + 1, by omega⟩
            (by show 0 < 1; omega) (by show 0 < i.val + 1; omega) (Fin.ext heq)
          have hval : (1 : Nat) = i.val + 1 := congrArg Fin.val hfin
          omega
        simp only [path']
        rw [Nat.testBit_or, h1, testBit_one_shiftLeft_ne w.val _ hne]
        rfl
      · intro i j hi hj heq
        have hfin := hinj ⟨i.val + 1, by omega⟩ ⟨j.val + 1, by omega⟩
          (by show 0 < i.val + 1; omega) (by show 0 < j.val + 1; omega) heq
        exact Fin.ext (by have : i.val + 1 = j.val + 1 := congrArg Fin.val hfin; omega)

/-- **Soundness of `hasCycleDfs`**: if `G.hasCycleDfs L = false`, then `¬ G.HasCycle L`. -/
theorem not_hasCycle_of_dfs (G : FinGraph n) (L : Nat) (hcheck : G.hasCycleDfs L = false) :
    ¬ G.HasCycle L := by
  rintro ⟨c⟩
  obtain ⟨c', hcanon⟩ := c.exists_canonical
  have hL := c'.hlen
  let s := c'.vert ⟨0, by omega⟩
  let path : Fin (L + 1) → Fin n := fun i =>
    if hi : i.val < L then c'.vert ⟨i.val, hi⟩ else s
  have htrue : hasPathBack G.adjArray s s L (1 <<< s.val) = true := by
    apply hasPathBack_complete G s L s (1 <<< s.val) path (by omega)
    · simp [path, s, show 0 < L by omega]
    · simp [path]
    · intro i
      have he := c'.edge i
      by_cases hi1 : i.val + 1 < L
      · have hmod : (i.val + 1) % L = i.val + 1 := Nat.mod_eq_of_lt hi1
        simp only [path, i.isLt, hi1, ↓reduceDIte]
        simpa [hmod] using he
      · have hieq : i.val + 1 = L := by omega
        have hmod : (i.val + 1) % L = 0 := by rw [hieq, Nat.mod_self]
        simp only [path, i.isLt, show ¬(i.val + 1 < L) by omega, ↓reduceDIte, s]
        simpa [hmod] using he
    · intro i hi
      simp only [path, i.isLt, ↓reduceDIte]
      exact hcanon i (by omega)
    · intro i hi
      simp only [path, i.isLt, ↓reduceDIte]
      have hgt := hcanon i (by omega)
      exact testBit_one_shiftLeft_ne s.val (c'.vert i).val (by omega)
    · intro i j _ _ heq
      simp only [path, i.isLt, j.isLt, ↓reduceDIte] at heq
      exact c'.inj i j heq
  have hmem : s ∈ List.finRange n := List.mem_finRange s
  have hany : G.hasCycleDfs L = true := by
    simp only [hasCycleDfs, List.any_eq_true]
    exact ⟨s, hmem, htrue⟩
  rw [hcheck] at hany
  exact Bool.false_ne_true hany

/-! ### 2. Provably Sound Weighted Short-Cycle DFS for Base Graphs (`checkWeightedCycles`) -/

/-- Exact recursive DFS checking that every canonical simple cycle of length `3 ≤ k ≤ maxLen`
    in a base graph `B` has `k + ∑_{i} w(prev_i, v_i, next_i) ≥ minReq`. -/
def checkWeightedAux (adj : Array (List (Fin n)))
    (w : Fin n → Fin n → Fin n → Nat) (minReq : Nat)
    (s first prev cur : Fin n) (len acc vis : Nat) : Nat → Bool
  | 0 => true
  | fuel + 1 =>
    let closeOk : Bool :=
      if len ≥ 2 && (adj.getD cur.val []).contains s then
        let total := (len + 1) + acc + w prev cur s + w cur s first
        decide (minReq ≤ total)
      else
        true
    if !closeOk then false
    else if fuel == 0 then true
    else
      (adj.getD cur.val []).all fun nxt =>
        if s.val < nxt.val && !vis.testBit nxt.val then
          checkWeightedAux adj w minReq s first cur nxt
            (len + 1) (acc + w prev cur nxt) (vis ||| (1 <<< nxt.val)) fuel
        else
          true

/-- Check every simple cycle of `B` of length `3 ≤ k ≤ maxLen` against `minReq`. -/
def checkWeightedCycles (B : FinGraph n) (w : Fin n → Fin n → Fin n → Nat)
    (maxLen minReq : Nat) : Bool :=
  let adj := B.adjArray
  (List.finRange n).all fun s =>
    (adj.getD s.val []).all fun first =>
      if s.val < first.val then
        checkWeightedAux adj w minReq s first s first 1 0
          ((1 <<< s.val) ||| (1 <<< first.val)) (maxLen - 1)
      else
        true

/-- Cyclic sum of `w(prev, cur, next)` over a simple cycle `c` of length `L`. -/
def cycleWeightSum {B : FinGraph n} {L : Nat} (c : SimpleCycle B L)
    (w : Fin n → Fin n → Fin n → Nat) : Nat :=
  (List.finRange L).foldl (fun acc i =>
    let prev := c.vert ⟨(i.val + L - 1) % L, Nat.mod_lt _ (by have := c.hlen; omega)⟩
    let cur  := c.vert i
    let nxt  := c.vert ⟨(i.val + 1) % L, Nat.mod_lt _ (by have := c.hlen; omega)⟩
    acc + w prev cur nxt) 0

/-- Partial sum of `w(c(i-1), c(i), c(i+1))` for `1 ≤ i < d`. -/
def partialWeight {B : FinGraph n} {L : Nat} (c : SimpleCycle B L)
    (w : Fin n → Fin n → Fin n → Nat) : Nat → Nat
  | 0 => 0
  | 1 => 0
  | d + 2 =>
    if hd : d + 2 < L then
      partialWeight c w (d + 1) +
        w (c.vert ⟨d, by omega⟩) (c.vert ⟨d + 1, by omega⟩) (c.vert ⟨d + 2, hd⟩)
    else
      partialWeight c w (d + 1)

theorem foldl_add_shift {α : Type} (f : α → Nat) (xs : List α) (init : Nat) :
    xs.foldl (fun a x => a + f x) init = init + xs.foldl (fun a x => a + f x) 0 := by
  induction xs generalizing init with
  | nil => simp
  | cons x xs ih =>
    simp only [List.foldl_cons, Nat.zero_add]
    rw [ih (init + f x), ih (f x)]
    omega

theorem cycleWeightSum_eq_partial {B : FinGraph n} {L : Nat} (c : SimpleCycle B L)
    (w : Fin n → Fin n → Fin n → Nat) :
    cycleWeightSum c w =
      partialWeight c w (L - 1) +
      w (c.vert ⟨L - 2, by have := c.hlen; omega⟩)
        (c.vert ⟨L - 1, by have := c.hlen; omega⟩)
        (c.vert ⟨0, by have := c.hlen; omega⟩) +
      w (c.vert ⟨L - 1, by have := c.hlen; omega⟩)
        (c.vert ⟨0, by have := c.hlen; omega⟩)
        (c.vert ⟨1, by have := c.hlen; omega⟩) := by
  have hL := c.hlen
  let f : Fin L → Nat := fun i =>
    let prev := c.vert ⟨(i.val + L - 1) % L, Nat.mod_lt _ (by omega)⟩
    let cur  := c.vert i
    let nxt  := c.vert ⟨(i.val + 1) % L, Nat.mod_lt _ (by omega)⟩
    w prev cur nxt
  change (List.finRange L).foldl (fun a i => a + f i) 0 = _
  have htake_sum : ∀ (d : Nat) (hd1 : 1 ≤ d) (hdL : d ≤ L - 1),
      ((List.finRange L).take d).foldl (fun a i => a + f i) 0 =
        f ⟨0, by omega⟩ + partialWeight c w d := by
    intro d
    induction d with
    | zero => intro h; omega
    | succ d ih =>
      intro _ hdL
      cases d with
      | zero =>
        have ht : (List.finRange L).take 1 = [⟨0, by omega⟩] := by
          apply List.ext_getElem
          · simp; omega
          · intro idx h1 h2
            have : idx = 0 := by simp at h2; omega
            subst this; simp
        rw [ht]
        simp [partialWeight]
      | succ d' =>
        have ht : (List.finRange L).take (d' + 2) =
            (List.finRange L).take (d' + 1) ++ [⟨d' + 1, by omega⟩] := by
          apply List.ext_getElem
          · simp; omega
          · intro idx h1 h2
            by_cases hlt : idx < d' + 1
            · rw [List.getElem_append_left (by simp; omega)]
              simp
            · have heq : idx = d' + 1 := by simp at h1; omega
              subst heq
              rw [List.getElem_append_right (by simp; omega)]
              simp [show d' + 1 - min (d' + 1) L = 0 by omega]
        rw [ht, List.foldl_append, foldl_add_shift, ih (by omega) (by omega)]
        simp only [List.foldl_cons, List.foldl_nil, Nat.zero_add]
        have hltL : d' + 2 < L := by omega
        simp only [partialWeight, hltL, ↓reduceDIte]
        have hm1 : (d' + 1 + L - 1) % L = d' := by
          rw [show d' + 1 + L - 1 = d' + L by omega, Nat.add_mod_right, Nat.mod_eq_of_lt (by omega)]
        have hm2 : (d' + 1 + 1) % L = d' + 2 := Nat.mod_eq_of_lt hltL
        have hf : f ⟨d' + 1, by omega⟩ =
            w (c.vert ⟨d', by omega⟩) (c.vert ⟨d' + 1, by omega⟩) (c.vert ⟨d' + 2, hltL⟩) := by
          simp [f, hm2, Nat.mod_eq_of_lt (by omega : d' < L)]
        rw [hf]; omega
  have hfull : List.finRange L = (List.finRange L).take (L - 1) ++ [⟨L - 1, by omega⟩] := by
    apply List.ext_getElem
    · simp; omega
    · intro idx h1 h2
      by_cases hlt : idx < L - 1
      · rw [List.getElem_append_left (by simp; omega)]; simp
      · have heq : idx = L - 1 := by simp at h1; omega
        subst heq
        rw [List.getElem_append_right (by simp)]
        simp
  rw [hfull, List.foldl_append, foldl_add_shift, htake_sum (L - 1) (by omega) (Nat.le_refl _)]
  simp only [List.foldl_cons, List.foldl_nil, Nat.zero_add]
  have hm0b : (0 + 1) % L = 1 := Nat.mod_eq_of_lt (by omega)
  have hmla : (L - 1 + L - 1) % L = L - 2 := by
    rw [show L - 1 + L - 1 = (L - 2) + L by omega, Nat.add_mod_right, Nat.mod_eq_of_lt (by omega)]
  have hmlb : (L - 1 + 1) % L = 0 := by
    rw [show L - 1 + 1 = L by omega, Nat.mod_self]
  have hf0 : f ⟨0, by omega⟩ =
      w (c.vert ⟨L - 1, by omega⟩) (c.vert ⟨0, by omega⟩) (c.vert ⟨1, by omega⟩) := by
    simp [f, hm0b, Nat.mod_eq_of_lt (by omega : L - 1 < L)]
  have hfl : f ⟨L - 1, by omega⟩ =
      w (c.vert ⟨L - 2, by omega⟩) (c.vert ⟨L - 1, by omega⟩) (c.vert ⟨0, by omega⟩) := by
    simp [f, hmla, hmlb]
  rw [hf0, hfl]; omega

theorem checkWeightedAux_sound (B : FinGraph n) (w : Fin n → Fin n → Fin n → Nat)
    (minReq : Nat) {L : Nat} (c : SimpleCycle B L)
    (hcanon : ∀ j : Fin L, j.val ≠ 0 → (c.vert ⟨0, by have := c.hlen; omega⟩).val < (c.vert j).val) :
    ∀ (fuel len : Nat) (_hlen1 : 1 ≤ len) (hlenL : len < L) (_hfuel : L - len ≤ fuel)
      (vis : Nat)
      (_hvis : ∀ j : Fin L, len < j.val → vis.testBit (c.vert j).val = false),
      checkWeightedAux B.adjArray w minReq
        (c.vert ⟨0, by have := c.hlen; omega⟩)
        (c.vert ⟨1, by have := c.hlen; omega⟩)
        (c.vert ⟨len - 1, by omega⟩)
        (c.vert ⟨len, hlenL⟩)
        len (partialWeight c w len) vis fuel = true →
      minReq ≤ L + cycleWeightSum c w := by
  intro fuel
  induction fuel with
  | zero => intro len _ hlenL hfuel; omega
  | succ fuel ih =>
    intro len hlen1 hlenL hfuel vis hvis hok
    have hL := c.hlen
    simp only [checkWeightedAux] at hok
    by_cases hlast : len = L - 1
    · have hge2 : len ≥ 2 := by omega
      have hadj_close : (B.adjArray.getD (c.vert ⟨len, hlenL⟩).val []).contains (c.vert ⟨0, by omega⟩) = true := by
        rw [getD_adjArray, List.contains_eq_mem, decide_eq_true_eq, mem_neighbors_iff]
        have he := c.edge ⟨L - 1, by omega⟩
        have hmod : (L - 1 + 1) % L = 0 := by rw [show L - 1 + 1 = L by omega, Nat.mod_self]
        have hidx : (⟨len, hlenL⟩ : Fin L) = ⟨L - 1, by omega⟩ := Fin.ext hlast
        rw [hidx]
        simpa [hmod] using he
      simp only [hge2, hadj_close, decide_true, Bool.and_self, ↓reduceIte] at hok
      by_cases hdec : minReq ≤ (len + 1) + partialWeight c w len +
          w (c.vert ⟨len - 1, by omega⟩) (c.vert ⟨len, hlenL⟩) (c.vert ⟨0, by omega⟩) +
          w (c.vert ⟨len, hlenL⟩) (c.vert ⟨0, by omega⟩) (c.vert ⟨1, by omega⟩)
      · rw [cycleWeightSum_eq_partial]
        have hlen1' : len + 1 = L := by omega
        have h1 : (⟨len - 1, by omega⟩ : Fin L) = ⟨L - 2, by omega⟩ := Fin.ext (by show len - 1 = L - 2; omega)
        have h2 : (⟨len, hlenL⟩ : Fin L) = ⟨L - 1, by omega⟩ := Fin.ext hlast
        have hpw : partialWeight c w len = partialWeight c w (L - 1) := congrArg (partialWeight c w) hlast
        rw [hlen1', h1, h2] at hdec
        omega
      · simp [hdec] at hok
    · have hlt_last : len + 1 < L := by omega
      have hfuel_pos : fuel ≠ 0 := by omega
      have hall : ∀ nxt ∈ B.adjArray.getD (c.vert ⟨len, hlenL⟩).val [],
          (if (c.vert ⟨0, by omega⟩).val < nxt.val && !vis.testBit nxt.val then
            checkWeightedAux B.adjArray w minReq
              (c.vert ⟨0, by omega⟩) (c.vert ⟨1, by omega⟩)
              (c.vert ⟨len, hlenL⟩) nxt
              (len + 1) (partialWeight c w len + w (c.vert ⟨len - 1, by omega⟩) (c.vert ⟨len, hlenL⟩) nxt)
              (vis ||| (1 <<< nxt.val)) fuel
          else true) = true := by
        cases hclose : (if (decide (len ≥ 2) && (B.adjArray.getD (c.vert ⟨len, hlenL⟩).val []).contains (c.vert ⟨0, by omega⟩)) = true then
            decide (minReq ≤ len + 1 + partialWeight c w len +
              w (c.vert ⟨len - 1, by omega⟩) (c.vert ⟨len, hlenL⟩) (c.vert ⟨0, by omega⟩) +
              w (c.vert ⟨len, hlenL⟩) (c.vert ⟨0, by omega⟩) (c.vert ⟨1, by omega⟩))
            else true)
        · rw [hclose] at hok; simp at hok
        · rw [hclose] at hok
          simp only [Bool.not_true, Bool.false_eq_true, ↓reduceIte, beq_iff_eq, hfuel_pos] at hok
          exact List.all_eq_true.mp hok
      let nxt := c.vert ⟨len + 1, hlt_last⟩
      have hmem : nxt ∈ B.adjArray.getD (c.vert ⟨len, hlenL⟩).val [] := by
        rw [getD_adjArray, mem_neighbors_iff]
        have he := c.edge ⟨len, hlenL⟩
        have hmod : (len + 1) % L = len + 1 := Nat.mod_eq_of_lt hlt_last
        simpa [nxt, hmod] using he
      have hstep := hall nxt hmem
      have hgt : (c.vert ⟨0, by omega⟩).val < nxt.val :=
        hcanon ⟨len + 1, hlt_last⟩ (by show len + 1 ≠ 0; omega)
      have hvis_nxt : vis.testBit nxt.val = false :=
        hvis ⟨len + 1, hlt_last⟩ (by show len < len + 1; omega)
      have hcond : (decide ((c.vert ⟨0, by omega⟩).val < nxt.val) && !vis.testBit nxt.val) = true := by
        simp [hgt, hvis_nxt]
      simp only [hcond, ↓reduceIte] at hstep
      have hpw : partialWeight c w (len + 1) =
          partialWeight c w len + w (c.vert ⟨len - 1, by omega⟩) (c.vert ⟨len, hlenL⟩) nxt := by
        cases len with
        | zero => omega
        | succ m =>
          simp only [partialWeight, hlt_last, ↓reduceDIte, nxt]
          congr 2
      rw [← hpw] at hstep
      apply ih (len + 1) (by omega) hlt_last (by omega) (vis ||| (1 <<< nxt.val))
      · intro j hj
        have h1 := hvis j (by omega)
        have hne : nxt.val ≠ (c.vert j).val := fun heq => by
          have := c.inj ⟨len + 1, hlt_last⟩ j (Fin.ext heq)
          have : len + 1 = j.val := congrArg Fin.val this
          omega
        rw [Nat.testBit_or, h1, testBit_one_shiftLeft_ne nxt.val _ hne]
        rfl
      · exact hstep

theorem cycleWeightSum_rotate_one {B : FinGraph n} {L : Nat} (c1 : SimpleCycle B L)
    (w : Fin n → Fin n → Fin n → Nat) :
    cycleWeightSum (c1.rotate 1) w = cycleWeightSum c1 w := by
  have hL := c1.hlen
  let f1 : Fin L → Nat := fun i =>
    w (c1.vert ⟨(i.val + L - 1) % L, Nat.mod_lt _ (by omega)⟩)
      (c1.vert i)
      (c1.vert ⟨(i.val + 1) % L, Nat.mod_lt _ (by omega)⟩)
  have hrel : ∀ i : Fin L,
      w ((c1.rotate 1).vert ⟨(i.val + L - 1) % L, Nat.mod_lt _ (by omega)⟩)
        ((c1.rotate 1).vert i)
        ((c1.rotate 1).vert ⟨(i.val + 1) % L, Nat.mod_lt _ (by omega)⟩) =
      f1 ⟨(i.val + 1) % L, Nat.mod_lt _ (by omega)⟩ := by
    intro i
    simp only [SimpleCycle.rotate, f1]
    have hm1 : ((i.val + L - 1) % L + 1) % L = ((i.val + 1) % L + L - 1) % L := by
      have h1 : ((i.val + L - 1) % L + 1) % L = i.val := by
        rw [Nat.mod_add_mod, show i.val + L - 1 + 1 = i.val + L by omega,
            Nat.add_mod_right, Nat.mod_eq_of_lt i.isLt]
      have h2 : ((i.val + 1) % L + L - 1) % L = i.val := by
        by_cases hlt : i.val + 1 < L
        · rw [Nat.mod_eq_of_lt hlt, show i.val + 1 + L - 1 = i.val + L by omega,
              Nat.add_mod_right, Nat.mod_eq_of_lt i.isLt]
        · have heq : i.val + 1 = L := by omega
          rw [heq, Nat.mod_self, show 0 + L - 1 = L - 1 by omega, Nat.mod_eq_of_lt (by omega)]
          omega
      rw [h1, h2]
    simp only [hm1]
  change (List.finRange L).foldl (fun a i => a + _) 0 = (List.finRange L).foldl (fun a i => a + f1 i) 0
  have hmap : (List.finRange L).foldl (fun a i =>
        a + w ((c1.rotate 1).vert ⟨(i.val + L - 1) % L, Nat.mod_lt _ (by omega)⟩)
              ((c1.rotate 1).vert i)
              ((c1.rotate 1).vert ⟨(i.val + 1) % L, Nat.mod_lt _ (by omega)⟩)) 0 =
      ((List.finRange L).map (fun i => (⟨(i.val + 1) % L, Nat.mod_lt _ (by omega)⟩ : Fin L))).foldl
        (fun a i => a + f1 i) 0 := by
    rw [List.foldl_map]
    congr 1; funext a i; rw [hrel i]
  rw [hmap]
  have hsplit1 : List.finRange L = ⟨0, by omega⟩ :: (List.finRange L).tail := by
    cases h : List.finRange L with
    | nil =>
      have : (List.finRange L).length = 0 := by rw [h]; rfl
      simp at this; omega
    | cons x xs =>
      have hx : x = ⟨0, by omega⟩ := by
        have h0 := congrArg (fun l => l[0]?) h
        simp [show 0 < L by omega] at h0
        exact h0.symm
      rw [hx]; rfl
  have hsplit2 : (List.finRange L).map (fun i => (⟨(i.val + 1) % L, Nat.mod_lt _ (by omega)⟩ : Fin L)) =
      (List.finRange L).tail ++ [⟨0, by omega⟩] := by
    apply List.ext_getElem
    · simp; omega
    · intro idx h1 h2
      simp only [List.getElem_map, List.getElem_finRange]
      by_cases hlt : idx < L - 1
      · rw [List.getElem_append_left (by simp; omega)]
        rw [List.getElem_tail]
        simp [Nat.mod_eq_of_lt (by omega : idx + 1 < L)]
      · have heq : idx = L - 1 := by simp at h1; omega
        subst heq
        rw [List.getElem_append_right (by simp)]
        simp [show (L - 1 + 1) % L = 0 by rw [show L - 1 + 1 = L by omega, Nat.mod_self]]
  rw [hsplit2, List.foldl_append, foldl_add_shift]
  have hfold1 : (List.finRange L).foldl (fun a i => a + f1 i) 0 =
      f1 ⟨0, by omega⟩ + (List.finRange L).tail.foldl (fun a i => a + f1 i) 0 := by
    have hcons : ((⟨0, by omega⟩ : Fin L) :: (List.finRange L).tail).foldl (fun a i => a + f1 i) 0 =
        f1 ⟨0, by omega⟩ + (List.finRange L).tail.foldl (fun a i => a + f1 i) 0 := by
      simp only [List.foldl_cons, Nat.zero_add]
      exact foldl_add_shift f1 (List.finRange L).tail (f1 ⟨0, by omega⟩)
    rw [← hsplit1] at hcons
    exact hcons
  rw [hfold1]
  simp only [List.foldl_cons, List.foldl_nil, Nat.zero_add]
  omega

theorem cycleWeightSum_rotate {B : FinGraph n} {L : Nat} (c0 : SimpleCycle B L) (r : Nat)
    (w : Fin n → Fin n → Fin n → Nat) :
    cycleWeightSum (c0.rotate r) w = cycleWeightSum c0 w := by
  induction r with
  | zero =>
    have heq : c0.rotate 0 = c0 := by
      cases c0 with
      | mk hlen vert inj edge =>
        simp only [SimpleCycle.rotate]
        congr 1; funext i; congr 1; apply Fin.ext; simp [Nat.mod_eq_of_lt i.isLt]
    rw [heq]
  | succ r ih =>
    have hcomp : c0.rotate (r + 1) = (c0.rotate r).rotate 1 := by
      cases c0 with
      | mk hlen vert inj edge =>
        simp only [SimpleCycle.rotate]
        congr 1; funext i; congr 1; apply Fin.ext
        change (i.val + (r + 1)) % L = ((i.val + 1) % L + r) % L
        rw [Nat.mod_add_mod]; congr 1; omega
    rw [hcomp, cycleWeightSum_rotate_one, ih]

/-- **Soundness of `checkWeightedCycles`**:
    If `B.checkWeightedCycles w maxLen minReq = true`, then EVERY simple cycle `c` of `B`
    of length `L ≤ maxLen` satisfies `L + cycleWeightSum c w ≥ minReq`. -/
theorem weighted_cycle_lower_of_check (B : FinGraph n)
    (w : Fin n → Fin n → Fin n → Nat) (maxLen minReq : Nat)
    (hcheck : B.checkWeightedCycles w maxLen minReq = true)
    {L : Nat} (c : SimpleCycle B L) (hLmax : L ≤ maxLen) :
    minReq ≤ L + cycleWeightSum c w := by
  obtain ⟨i0, hi0⟩ := c.exists_min_pos
  let c' := c.rotate i0.val
  have hcanon : ∀ j : Fin L, j.val ≠ 0 → (c'.vert ⟨0, by have := c.hlen; omega⟩).val < (c'.vert j).val := by
    intro j hj
    have hL := c.hlen
    have h0 : c'.vert ⟨0, by omega⟩ = c.vert i0 := by
      simp [c', SimpleCycle.rotate, Nat.mod_eq_of_lt i0.isLt]
    rw [h0]
    have hle := hi0 ⟨(j.val + i0.val) % L, Nat.mod_lt _ (by omega)⟩
    have hne : c'.vert ⟨0, by omega⟩ ≠ c'.vert j := fun heq => by
      have := c'.inj _ _ heq
      exact hj (congrArg Fin.val this).symm
    rw [h0] at hne
    have hval_ne : (c.vert i0).val ≠ (c'.vert j).val := fun h => hne (Fin.ext h)
    change (c.vert i0).val < (c.vert ⟨(j.val + i0.val) % L, _⟩).val
    change (c.vert i0).val ≠ (c.vert ⟨(j.val + i0.val) % L, _⟩).val at hval_ne
    omega
  rw [← cycleWeightSum_rotate c i0.val w]
  have hL := c'.hlen
  let s := c'.vert ⟨0, by omega⟩
  let first := c'.vert ⟨1, by omega⟩
  simp only [checkWeightedCycles, List.all_eq_true] at hcheck
  have hs := hcheck s (List.mem_finRange s)
  have hmem1 : first ∈ B.adjArray.getD s.val [] := by
    rw [getD_adjArray, mem_neighbors_iff]
    have he := c'.edge ⟨0, by omega⟩
    have hmod : (0 + 1) % L = 1 := Nat.mod_eq_of_lt (by omega)
    simpa [s, first, hmod] using he
  have h1 := hs first hmem1
  have hgt1 : s.val < first.val := hcanon ⟨1, by omega⟩ (by show 1 ≠ 0; omega)
  simp only [hgt1, ↓reduceIte] at h1
  apply checkWeightedAux_sound B w minReq c' hcanon (maxLen - 1) 1 (by omega) (by omega) (by omega)
    ((1 <<< s.val) ||| (1 <<< first.val))
  · intro j hj
    have hne0 : s.val ≠ (c'.vert j).val := fun h => by
      have := c'.inj ⟨0, by omega⟩ j (Fin.ext h)
      have : (0 : Nat) = j.val := congrArg Fin.val this
      omega
    have hne1 : first.val ≠ (c'.vert j).val := fun h => by
      have := c'.inj ⟨1, by omega⟩ j (Fin.ext h)
      have : (1 : Nat) = j.val := congrArg Fin.val this
      omega
    rw [Nat.testBit_or, testBit_one_shiftLeft_ne s.val _ hne0,
        testBit_one_shiftLeft_ne first.val _ hne1]
    rfl
  · simpa [partialWeight, s, first] using h1

end FinGraph
end Sglab
