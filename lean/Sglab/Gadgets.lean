import Sglab.Graph
import Sglab.GadgetLift

/-!
# Sglab.Gadgets — Kernel-Verified 3-Port Gadgets `H_7`, `H_8*`, and `H_15`

Defines the three 3-port vertex-replacement gadgets discovered and used in our
extremal `{C4, C8, C16, C32, C64}`-free constructions, and proves with zero `sorry`,
zero custom axioms, and zero `native_decide`:
  - `H7` (`n = 7`, cubic-internal, `{C4, C8}`-free, port distances `(2, 2, 3)`),
  - `H8star` (`n = 8`, `δ ≥ 3` with one deg-4 apex, `{C4, C8}`-free, port distances `(3, 3, 2)`),
  - `H15` (`n = 15`, cubic-internal, `{C4, C8}`-free, port distances `(3, 3, 5)`).

Every port-to-port distance lower bound is certified by an explicit BFS potential
`φ : Fin n → Nat` via `FinGraph.dist_lower_of_potential`, and every local cycle
absence (`¬ HasCycle 4`, `¬ HasCycle 8`) is certified by `FinGraph.not_hasCycle_of_dfs`.
-/

namespace Sglab
open FinGraph

/-- Construct a `FinGraph n` from an undirected edge list (automatically symmetric and loopless). -/
def FinGraph.ofEdgeList (n : Nat) (edges : List (Nat × Nat)) : FinGraph n where
  adj u v :=
    u.val != v.val && edges.any (fun e => (e.1 == u.val && e.2 == v.val) || (e.1 == v.val && e.2 == u.val))
  symm u v := by
    have hne : (u.val != v.val) = (v.val != u.val) := by
      by_cases h : u.val = v.val
      · simp [h]
      · have h2 : v.val ≠ u.val := Ne.symm h
        simp only [bne, beq_false_of_ne h, beq_false_of_ne h2]
    have hany : edges.any (fun e => (e.1 == u.val && e.2 == v.val) || (e.1 == v.val && e.2 == u.val)) =
                edges.any (fun e => (e.1 == v.val && e.2 == u.val) || (e.1 == u.val && e.2 == v.val)) := by
      congr 1; funext e; exact Bool.or_comm _ _
    rw [hne, hany]
  loopless u := by simp

/-- Helper: build a `Gadget3` distance lower bound proof from 3 BFS potential arrays `φ0, φ1, φ2`
    (one per port `a : Fin 3`). -/
theorem distLower_of_potentials {m : Nat} (G : FinGraph m) (port : Fin 3 → Fin m)
    (dl : Fin 3 → Fin 3 → Nat)
    (φ : Fin 3 → Fin m → Nat)
    (h0 : ∀ a : Fin 3, φ a (port a) = 0)
    (hstep : ∀ (a : Fin 3) (u v : Fin m), G.adj u v = true → φ a v ≤ φ a u + 1)
    (hbound : ∀ a b : Fin 3, a ≠ b → dl a b ≤ φ a (port b)) :
    ∀ (a b : Fin 3) (d : Nat), a ≠ b → G.SimplePath (port a) (port b) d → dl a b ≤ d := by
  intro a b d hne p
  have h1 := dist_lower_of_potential G (φ a) (port a) (port b) d p (h0 a) (hstep a)
  exact Nat.le_trans (hbound a b hne) h1

/-- Look up an entry in a `Nat` list by `Fin m` index. -/
def listAt {m : Nat} (xs : List Nat) (i : Fin m) : Nat :=
  xs.getD i.val 0

/-! ### 1. Gadget `H_7` (`n = 7`, cubic-internal, port distances `(2, 2, 3)`) -/

def H7_edges : List (Nat × Nat) :=
  [(0, 3), (0, 4), (1, 3), (1, 5), (2, 4), (2, 6), (3, 5), (4, 6), (5, 6)]

def H7_graph : FinGraph 7 := FinGraph.ofEdgeList 7 H7_edges

def H7_port : Fin 3 → Fin 7
  | ⟨0, _⟩ => ⟨0, by omega⟩
  | ⟨1, _⟩ => ⟨1, by omega⟩
  | ⟨2, _⟩ => ⟨2, by omega⟩

/-- Port-to-port distance lower bounds for `H_7`:
    port `0` is the weak port (`d(0,1)=2, d(0,2)=2`), while `d(1,2)=3`. -/
def H7_dl (a b : Fin 3) : Nat :=
  if a == b then 0 else if a.val == 0 || b.val == 0 then 2 else 3

def H7_phi : Fin 3 → Fin 7 → Nat
  | ⟨0, _⟩ => listAt [0, 2, 2, 1, 1, 2, 2]
  | ⟨1, _⟩ => listAt [2, 0, 3, 1, 3, 1, 2]
  | ⟨2, _⟩ => listAt [2, 3, 0, 3, 1, 2, 1]

def H7 : Gadget3 where
  order := 7
  hpos := by omega
  graph := H7_graph
  port := H7_port
  isUnit := false
  port_inj := by decide
  unit_order := by decide
  distLower := H7_dl
  distLower_symm := by decide
  distLower_sound :=
    distLower_of_potentials H7_graph H7_port H7_dl H7_phi
      (by decide) (by decide) (by decide)
  deg_ok := by decide

theorem H7_isCubicInternal : H7.IsCubicInternal := Or.inr (by decide)

theorem H7_no_C4 : ¬ H7.graph.HasCycle 4 :=
  not_hasCycle_of_dfs H7.graph 4 (by decide)

theorem H7_no_C8 : ¬ H7.graph.HasCycle 8 :=
  not_hasCycle_of_order_lt H7.graph (by decide)

/-! ### 2. Gadget `H_8*` (`n = 8`, `δ ≥ 3`, port distances `(3, 3, 2)`) -/

def H8star_edges : List (Nat × Nat) :=
  [(0, 3), (0, 4), (1, 3), (1, 6), (2, 5), (2, 7), (3, 5), (4, 6), (4, 7), (5, 7), (6, 7)]

def H8star_graph : FinGraph 8 := FinGraph.ofEdgeList 8 H8star_edges

/-- Port ordering for `H_8*`: slot `0` is vertex `2` (the distinguished "good" port,
    with `d(2, 0) = 3` and `d(2, 1) = 3`, while `d(0, 1) = 2`). -/
def H8star_port : Fin 3 → Fin 8
  | ⟨0, _⟩ => ⟨2, by omega⟩
  | ⟨1, _⟩ => ⟨0, by omega⟩
  | ⟨2, _⟩ => ⟨1, by omega⟩

def H8star_dl (a b : Fin 3) : Nat :=
  if a == b then 0 else if a.val == 0 || b.val == 0 then 3 else 2

def H8star_phi : Fin 3 → Fin 8 → Nat
  | ⟨0, _⟩ => listAt [3, 3, 0, 2, 2, 1, 2, 1]
  | ⟨1, _⟩ => listAt [0, 2, 3, 1, 1, 2, 2, 2]
  | ⟨2, _⟩ => listAt [2, 0, 3, 1, 2, 2, 1, 2]

def H8star : Gadget3 where
  order := 8
  hpos := by omega
  graph := H8star_graph
  port := H8star_port
  isUnit := false
  port_inj := by decide
  unit_order := by decide
  distLower := H8star_dl
  distLower_symm := by decide
  distLower_sound :=
    distLower_of_potentials H8star_graph H8star_port H8star_dl H8star_phi
      (by decide) (by decide) (by decide)
  deg_ok := by decide

theorem H8star_no_C4 : ¬ H8star.graph.HasCycle 4 :=
  not_hasCycle_of_dfs H8star.graph 4 (by decide)

theorem H8star_no_C8 : ¬ H8star.graph.HasCycle 8 :=
  not_hasCycle_of_dfs H8star.graph 8 (by decide)

/-! ### 3. Gadget `H_15` (`n = 15`, cubic-internal, port distances `(3, 3, 5)`) -/

def H15_edges : List (Nat × Nat) :=
  H7_edges ++
  H7_edges.map (fun e => (e.1 + 7, e.2 + 7)) ++
  [(14, 1), (14, 8), (2, 9)]

def H15_graph : FinGraph 15 := FinGraph.ofEdgeList 15 H15_edges

/-- Port ordering for `H_15`: slot `0` is vertex `14` (`d(14, 0) = 3, d(14, 7) = 3`),
    while slots `1, 2` are vertices `0, 7` (`d(0, 7) = 5`). -/
def H15_port : Fin 3 → Fin 15
  | ⟨0, _⟩ => ⟨14, by omega⟩
  | ⟨1, _⟩ => ⟨0, by omega⟩
  | ⟨2, _⟩ => ⟨7, by omega⟩

def H15_dl (a b : Fin 3) : Nat :=
  if a == b then 0 else if a.val == 0 || b.val == 0 then 3 else 5

def H15_phi : Fin 3 → Fin 15 → Nat
  | ⟨0, _⟩ => listAt [3, 1, 4, 2, 4, 2, 3, 3, 1, 4, 2, 4, 2, 3, 0]
  | ⟨1, _⟩ => listAt [0, 2, 2, 1, 1, 2, 2, 5, 4, 3, 5, 4, 5, 4, 3]
  | ⟨2, _⟩ => listAt [5, 4, 3, 5, 4, 5, 4, 0, 2, 2, 1, 1, 2, 2, 3]

def H15 : Gadget3 where
  order := 15
  hpos := by omega
  graph := H15_graph
  port := H15_port
  isUnit := false
  port_inj := by decide
  unit_order := by decide
  distLower := H15_dl
  distLower_symm := by decide
  distLower_sound :=
    distLower_of_potentials H15_graph H15_port H15_dl H15_phi
      (by decide) (by decide) (by decide)
  deg_ok := by decide

theorem H15_isCubicInternal : H15.IsCubicInternal := Or.inr (by decide)

theorem H15_no_C4 : ¬ H15.graph.HasCycle 4 :=
  not_hasCycle_of_dfs H15.graph 4 (by decide)

theorem H15_no_C8 : ¬ H15.graph.HasCycle 8 :=
  not_hasCycle_of_dfs H15.graph 8 (by decide)

/-! ### 4. Utility Port Permutation Mapping Distinguished Neighbor `c` to Slot `0` -/

/-- Cyclic permutation on `Fin 3` sending `c ↦ 0`. -/
def rotPerm (c : Fin 3) (k : Fin 3) : Fin 3 :=
  ⟨(k.val + 3 - c.val) % 3, Nat.mod_lt _ (by omega)⟩

theorem rotPerm_inj (c : Fin 3) : ∀ a b : Fin 3, rotPerm c a = rotPerm c b → a = b := by
  decide +revert

theorem rotPerm_self (c : Fin 3) : rotPerm c c = ⟨0, by omega⟩ := by
  decide +revert

end Sglab
