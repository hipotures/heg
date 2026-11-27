# Przegląd uzupełniający nr 2: commit `e7acb38` (erratum R2, DRAT, Phase R3)

- **Dotyczy**: `REVIEW_FOLLOWUP_2026_11_27.md` → `e7acb38` (`ERRATUM_2026_11_27_PHASE_R2.md`, `M6_GOAL_PHASE_R3_F4_DELTA3_LT73_2026_11_27.md`).
- **Ograniczenia**: maszyna była zajęta. Nie uruchamiano `cargo test` ani 16-wątkowego enumeratora gadżetów. Jedyne cięższe obliczenie to jednowątkowy CaDiCaL z `nice 19`, łącznie ok. 8 min CPU.
- **Nowy skrypt**: `docs/reports/assets/review-2026-11-26/tc_indep_lemma.py`.

## 1. Status uwag z `REVIEW_FOLLOWUP_2026_11_27.md`

| Uwaga | Status |
|---|---|
| Brak testu C8 dla krawędzi portowych i w liściu (4 porty) | ✅ Naprawione w kodzie. Według erratum po ponownym uruchomieniu wyniki 4-portowe się nie zmieniły. **Ponownego uruchomienia nie odtwarzałem** (wymaga 16 rdzeni) |
| Sygnatura z nieparzystą sumą, brakujące 2×deg4 dla n=13/17 | ✅ Asercja parzystości. Nowe sygnatury: n=13 i n=17 z 2×deg4, n=14 z 3×deg4 (warianty noPE). Zakres tezy sprecyzowany w erratum |
| Mieszana metryka „leaves” | ✅ Wyjaśnione w erratum |
| Brak kodu `NO_SB` | ✅ Dodany `verify_symmetry_breaking.cpp` |
| Kruchość `assign_v` | ✅ Naprawione |
| UNSAT z jednego solvera | ✅ SAT i DRAT własnymi narzędziami, plus **moja niezależna weryfikacja** (§2) |
| Ścieżki `~/.gemini` | ✅ Usunięte (`grep` zwraca pusto) |
| Surowe dane JSON | ✅ `docs/reports/data/` z `SHA256SUMS.txt` (sumy się zgadzają) |
| Dokumentacja CLI i ADR | ✅ `docs/reference/cli-rust-engine.md`, `docs/adr/0019-…` |
| Test `verify-large` | ✅ Komentarze poprawione, dodany test ABSENT na `n=370` (testu nie uruchamiałem) |

## 2. Niezależna weryfikacja UNSAT dla rodziny TC

Moje kodowanie, `tc_indep_lemma.py`, jest niezależne od `tc_to_cnf.py`, `mini_cdcl_drat.cpp` i `tc_exact_optimality.cpp`:
- graf TC zbudowany inaczej (graf Leviego GQ(2,2), a nie LCF);
- własne wyliczenie cykli C8/C10;
- własne kodowanie PB→CNF (monotoniczny DP sum prefiksowych);
- ograniczenie liczności z PySAT, rozwiązywanie uznanym solverem **CaDiCaL 1.5.3**;
- każdy model SAT sprawdzany osobno na wszystkich 162 cyklach.

| Instancja | Wynik | Czas (nice 19) |
|---|---|---:|
| ≤18·H15 + H7 (cubic, `n ≤ 354`) | **UNSAT** ✅ | 305 s |
| ≤14·H15 + H8* (δ≥3, `n ≤ 338`) | **UNSAT** ✅ | 21 s |
| ≤20·H15 + H7 (kontrola) | SAT, model sprawdzony, `n = 370` ✅ | 142 s |
| ≤15·H15 + H8* (kontrola) | SAT, model sprawdzony, `n = 345` ✅ | 22 s |

Uwagi:
- Bez lematu zliczającego CaDiCaL nie rozstrzygnął `n ≤ 354` w ~16 min CPU, więc przebieg przerwano. Oba wyniki UNSAT (projektu i mój) zależą więc od lematu `Σ_{C8}(Σw_C − 9) = 16a − 8b − 16c − 90`. Lemat sprawdziłem ręcznie: każda para (wierzchołek, para krawędzi) TC leży na dokładnie 8 z 90 ośmiocykli. Przy `AtMost(#H15 ≤ a)` lewa strona jest ≤ S(a). DRAT certyfikuje tylko CNF z lematem, a nie sam lemat — warto to dopisać w erratum.
- Hash `d42e49c4…` w erratum odtwarza się poleceniem `tc_to_cnf.py --a15 18 --g2 H7 --add-slack-bound`. Ta instancja obejmuje tylko C8 (relaksacja, co jest poprawne dla UNSAT), ale **flagi nie są udokumentowane**.
- Wniosek „TC + {H15, H8*, H7}: minimum δ≥3 w [342, 345], kubiczne ∈ {362, 370}” jest teraz potwierdzony niezależnie. Nadal obowiązuje on tylko wewnątrz tej rodziny.

## 3. Phase R3 (`f_{δ≥3}(4) < 73`)

- Kierunek zgodny z zaleceniem: 0% mocy na kubiczne `n < 78`.
- Wszystkie 6 grafów „best” z `phase_r3_f4_delta3_lt73_results.json` sprawdziłem niezależnie (`cyc.c`): stopnie, 2-spójność, C4 = C8 = 0, liczby C16 = 1, 2, 2, 10, 16, 12 — **zgodne** z raportem.
- Język nadal nadinterpretuje wyniki heurystyczne: „rock-solid C16 = 1 floor”, „Sharp empirical transition at n = 73 vs n = 72”. To wyniki LNS bez znaczenia dowodowego. Należy pisać „nie znaleziono C16 = 0 w N liściach”.

## 4. Pozostałe drobiazgi

1. Udokumentować dokładne polecenia generujące CNF, dla których podano hashe (`--add-slack-bound`, bez `--include-c10`) i zaznaczyć, że DRAT nie obejmuje lematu.
2. Złagodzić sformułowania „floor/transition” w R3.
