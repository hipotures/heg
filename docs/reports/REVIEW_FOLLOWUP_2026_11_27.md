# Przegląd uzupełniający: weryfikacja poprawek po recenzji i raportu Phase R2 (2026-11-27)

- **Dotyczy**: `REVIEW_M6_WAVES_D_F_TRACK2_2026_11_26.md` → commity `6f67c6c` (remediation + erratum) i `ebddd39` (Phase R2).
- **Ograniczenia**: maszyna nadal była zajęta, więc nie uruchamiano `cargo test`, `make test` ani 16-wątkowych solverów z `tools/extremal/`. Wykonano tylko lekkie, jednowątkowe sprawdzenia (`nice`).
- **Nowe skrypty**: `docs/reports/assets/review-2026-11-26/hc.c` (niezależne lokalne przeszukiwanie gadżetów) i `enum_n7_gadgets.py` (wyczerpująca enumeracja n=7).

## 1. Status uwag z recenzji

| § | Uwaga | Status |
|---|---|---|
| 3.1 | Ripatti 2017: kubiczne `n < 78` | ✅ Naprawione: `00_RESEARCH_STATUS.md` (zakaz takich kampanii), erratum §2.1 |
| 3.2 | Narzędzia poza repo | 🟡 Częściowo. Źródła są w `tools/extremal/`, certyfikat `n=77` dodany i niezależnie potwierdzony (`cyc.c`: brak C4/C8/C16). **Ale**: `f5_h8star_solver.cpp:366`, `f5_girth8_bipartite_assault.cpp:350`, `test_h8star_petersen_f4.py:22` i `track2_certify_all_f5.py:25` mają na sztywno wpisane ścieżki do `~/.gemini/.../scratch`. Surowe JSON-y kampanii 1h/2h/Wave E nadal nie są w repo. |
| 3.3 | „Unique/0 found” z próbkowania | ✅ Naprawione w erratum §2.3. Phase R2 dodał enumerację wyczerpującą (uwagi w §2) |
| 3.4 | Błędny pigeonhole w Wave E | ✅ Wycofane w erratum §2.2 |
| 3.5 | Atrybucja `f(6)` | ✅ Naprawione w erratum §2.4 i w statusie (32 640, arXiv:2511.07247 z XI 2025, bound warunkowy) |
| 3.6 | Przesadne sformułowania, heurystyki zamiast solvera dokładnego | ✅ Erratum §2.5. Phase R2 rozstrzyga `n=338` i `n=354` solverem dokładnym |
| 3.7.1 | Martwy BFS i mylący komentarz | ✅ Usunięte i poprawione |
| 3.7.2 | Świadek tylko w `debug_assert` | ✅ `verify_witness_runtime` działa także w release |
| 3.7.3 | `--lengths` i graph6 | ✅ Sprawdzone na zbudowanym binarium: `--lengths 4,8,1x` daje komunikat błędu i exit 2. Długość graph6 jest walidowana |
| 3.7.4 | Testy `n > 64` | 🟡 Testy pokrywają słowa maski 1–7 i bit 511. Komentarze w teście są jednak nieprawdziwe („cubic graph”, „chords every 10th vertex”, „n = 100”): grafy to cykl `C_300`/`C_512` z 1–2 cięciwami, a `n=100` nie jest testowane. Brak testu ABSENT na gęstym grafie `n > 128` (np. na samym certyfikacie `n=370`) |
| 3.8 | Tabela D2, sito Monte Carlo | ✅ Erratum §2.6 |
| 3.9 | Dokumentacja referencyjna/architektoniczna, ADR | ❌ **Nie zrobione**: nowe podkomendy (`verify-large`, `lns-polish`, `voltage-search`, `bjorklund-c32`) nadal są opisane tylko w ledgerze i raportach |

## 2. Phase R2: co potwierdzono, a co budzi wątpliwości

### 2.1 Potwierdzone niezależnie

- **Drugi świadek `n=73`** (`Petersen_1U_9H8star`): `m=114`, `{3:64, 4:9}`, brak punktów artykulacji, brak C4/C8/C16 (`cyc.c`) ✅
- **n=7: dokładnie dwa typy okien** (moja enumeracja wszystkich etykietowanych grafów, `enum_n7_gadgets.py`): `(2,2,2)` i `(2,2,3)`. **Wszystkie okna H7 są ciągłe**: `[2..6], [2..6], [3..6]`. Ma to znaczenie dla §2.3: model minimów okien jest dla rodziny `{H15, H8*, H7}` modelem dokładnym, a nie tylko relaksacją.
- **„0 gadżetów {C4,C8}-free dla n=11–14”**: niezależne lokalne przeszukiwanie (`hc.c`, 400 restartów × 4000 zamian) nie znalazło żadnego gadżetu dla `(2,2,2,3⁸)`, `(2,2,2,3⁸,4)`, `(2,2,2,3¹⁰)` ani `(2,2,2,3¹⁰,4)` noPE. Kontrola pozytywna: ten sam program znajduje gadżet `n=7` i gadżet `n=15` typu H15 (okna 3/3/5) w ułamku sekundy. Wynik jest zgodny z R2, choć to tylko dowód empiryczny.
- **Twierdzenie analityczne** `8a₁₅ − 4b₈ − 8c₇ ≥ 45` i wnioski z niego (`a ≥ 18` kubicznie, `a ≥ 14` dla δ≥3, `c ≤ 3` przy `a = 15`, co daje `n ≥ 342`) przeliczono ręcznie. Są poprawne.

### 2.2 Uwagi do `exhaustive_gadget_enum_deep.cpp` (klasyfikacja „100% exhaustive”)

1. **Przycinanie C8 jest wyłączone dla krawędzi z portów** (`if (u >= np && creates_c8(...))`), a liść **nie ma końcowego testu C8** (testowane są tylko C16 i tylko dla `n ≥ 16`). Dla 3 portów to nieszkodliwe: 6 krawędzi portowych nie zamknie C8. **Dla 4 portów** cykl `p0–i–p1–j–p2–k–p3–l` składa się wyłącznie z 8 krawędzi portowych, a zamyka go krawędź dodana przy `u = 3 < np`, której nikt nie sprawdza. Klasyfikacja 4-portowa (`Q₁₁…Q₁₄`) może więc zawierać fałszywe „{C4,C8}-free” gadżety. Wystarczy dodać `has_cycle_len(n, rows, 8)` w liściu.
2. **Pusta sygnatura**: `"3p n=14 2xdeg4 (2,2,2 + 9x3 + 4,4)"` ma sumę stopni 6+27+8 = **41 (nieparzystą)**, więc wynik „0” nic nie dowodzi.
3. **Brakujące sygnatury** wobec tezy „among all cubic, 1×deg4, and 2×deg4 … up to n = 17, ONLY THREE ORDERS EXIST”: nie uruchomiono `n=13, 2×deg4` (`2,2,2,3⁸,4,4`, suma 38) ani `n=17, 2×deg4` (`2,2,2,3¹²,4,4`, suma 50). Wierzchołki stopnia ≥ 5 pojawiają się tylko dla `n ≤ 9`. Teza jest za szeroka.
4. **Kolumna „{C4,C8}-free Leaves”** w tabeli R2 miesza dwie metryki. Dla `n ≤ 11` (część A, `exhaustive_gadget_enum.cpp`) to liście jedynie C4-free (np. 1170 dla `n=11`), a dla `n ≥ 12` (deep) to liście {C4,C8}-free. Stąd pozorna anomalia 1170 → 0 → 96.
5. **Weryfikacja „against brute-force NO_SB at n = 7, 8, 9”** nie ma kodu w repo, więc nie da się jej odtworzyć. Moja enumeracja potwierdza tylko `n=7`. Argument za bezstratnością łamania symetrii (izolowane wierzchołki tej samej klasy są wymienne, wybiera się „prefiks”) uważam za poprawny.

### 2.3 Uwagi do `tc_exact_optimality.cpp` (`PROVEN_UNSAT` dla `n=338` i `n=354`)

Logika jest poprawna:
- ograniczenie przez slack: suma niezależnych dolnych ograniczeń nieujemnych składników tożsamości `Σ_C(sum_C − 25) = 16a − 8b − 16c − 90`;
- `cycle_max_sum` jako górne ograniczenie;
- łamanie symetrii (`v=0`, `p0=0`) jest bezstratne, bo TC jest 5-łukowo-przechodni, a stabilizator wierzchołka działa na sąsiadach jak S₃;
- uwzględniono wszystkie 162 cykle (8 i 10), a dla `L ≥ 12` warunek zachodzi zawsze.

Zastrzeżenia:
1. **Utajona kruchość**: `assign_v` przerywa aktualizację w połowie listy cykli, a `unassign_to` cofa wszystkie cykle wierzchołka. Przy nieudanym przypisaniu w `dfs` stan zostałby uszkodzony (możliwe fałszywe UNSAT). Obecnie ta ścieżka się nie wykonuje, bo domena jest filtrowana tym samym testem, a w generowaniu zadań stany są kopiowane. To jednak pułapka przy każdej modyfikacji. Należy aktualizować wszystkie cykle przed zwróceniem `false` albo zapamiętywać liczbę zaktualizowanych.
2. **Brak niezależnego potwierdzenia**: UNSAT pochodzi z jednego, autorskiego solvera, bez certyfikatu dowodu. Status „Complete & Independently Verified” w nagłówku R2 dotyczy certyfikatów grafów, a nie dowodów UNSAT. Rekomendacja: zakodować instancję jako SAT/ILP i rozstrzygnąć ją niezależnie (np. CaDiCaL z DRAT) — instancja ma 30 × 9 zmiennych i 162 ograniczenia.
3. **Zakres**: „exact TC minimum [342, 345]” i „{362, 370}” obowiązują wyłącznie dla bazy TC i gadżetów `{H15, H8*, H7}`. Nie obejmują wierzchołków nierozwiniętych (`U`, jak w `Pet_1U`), gadżetów 4-portowych ani innych baz. Raport mówi to w jednym zdaniu, ale tytuł („Exact Optimality Theorems”) jest szerszy.

### 2.4 Pozostałe sformułowania R2

- §4 „larger bases cannot compensate” (bazy B₃₄…B₄₈) opiera się na minimalnych liczbach naruszeń z solvera heurystycznego, a nie na dowodzie. Należy pisać „nie znaleziono”.
- W ledgerze (`IMPLEMENTATION_STATUS.md`, wpis Track 2) nadal stoi „unique … H8*”. Erratum to prostuje, a ledger jest chronologiczny, więc jest to akceptowalne.

## 3. Zalecenia (krótko)

1. Dodać końcowy test C8 w liściu `exhaustive_gadget_enum_deep.cpp`, uruchomić ponownie część 4-portową i brakujące sygnatury 3-portowe (`n=13`/`n=17` z 2×deg4), a pustą sygnaturę `n=14 2×deg4` usunąć.
2. Zastąpić na sztywno wpisane ścieżki `~/.gemini/...` argumentami CLI lub ścieżkami względnymi w repo. Zaimportować surowe JSON-y kampanii albo podać ich hashe i lokalizację.
3. Niezależnie zweryfikować UNSAT dla `n=338`/`n=354` (SAT + DRAT) i usunąć kruchość `assign_v`.
4. Dodać dokumentację referencyjną nowych podkomend CLI. Rozważyć ADR dla ścieżki weryfikacji `n ≤ 512`.
5. Poprawić komentarze w teście `large_verify.rs` i dodać test ABSENT na certyfikacie `n=370`.
