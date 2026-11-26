# Przegląd krytyczny: Waves D1–F, kampanie LNS 1h/2h i Track 2 (2026-11-26)

- **Zakres**: commity `7eda717` … `7bb5a67` (Wave A+B+C campaign, D1, D2, 1h LNS, E, 2h ILS-LNS, F, Track 2).
- **Charakter**: niezależny przegląd poprawności, metodologii i wniosków. Nie zmienia żadnego wcześniejszego raportu (zgodnie z zasadą „reports are evidence”).
- **Ograniczenia przeglądu**: maszyna była w trakcie innego eksperymentu (load ≈ 16/16), więc **nie uruchamiano** `make test`, `cargo test`, kampanii ani budowania. Wykonano wyłącznie lekkie, jednowątkowe obliczenia (`nice`, łącznie < 15 s CPU). Pełnych tekstów cytowanych preprintów nie czytano — tylko abstrakty.
- **Skrypty weryfikacyjne**: `docs/reports/assets/review-2026-11-26/` (`g6.py`, `cyc.c`, `h8.py`, `pet.c`).

---

## 1. Werdykt w skrócie

| Twierdzenie | Status po przeglądzie |
|---|---|
| Certyfikat `f_cubic(5) ≤ 370` (`n=370`) | **Potwierdzone niezależnie** (graf jest 3-regularny, 2-spójny, nie ma C4/C8/C16/C32) |
| Certyfikat `f_{δ≥3}(5) ≤ 345` (`n=345`) | **Potwierdzone niezależnie** |
| Certyfikat `f_{δ≥3}(4) ≤ 73` (`n=73`) | **Potwierdzone niezależnie** |
| Gadżet `H8*`: okna ścieżek i cykle wewnętrzne | **Potwierdzone** |
| Brak rozwiązań `Petersen + 2·H8* + 8·H7` (`n=72`) | **Potwierdzone** (tylko w tej rodzinie konstrukcji) |
| „Poprzedni rekord” `f_cubic(5)=450` (García, arXiv:2609.04686) | Zgodne z abstraktem Garcíi |
| `f_cubic(6) ≤ 30 360` | Rozumowanie poprawne, ale **warunkowe** i z błędną atrybucją punktu odniesienia (§3.5) |
| H8* „unikalny”, brak gadżetów przy `n=9,11,13`, `H15` „unikalny” | **Nieudowodnione**: wynika z losowego próbkowania, a nie z wyczerpującego przeszukania (§3.3) |
| „Pigeonhole floor” `C16 ≥ 4` dla `Petersen + 10·H7` (Wave E) | **Dowód błędny**: rzeczywiste minimum to 2 złe 5-cykle (§3.4) |
| Kampanie kubiczne `n = 60…76` pod hasłem `f(4) < 78` | **Z góry bezcelowe**: Ripatti (2017) wykazał, że minimum kubiczne wynosi 78 (§3.1) |
| `f_{δ≥3}(4) ≤ 77` (Wave E) | **Brak artefaktu w repo**, wskazany plik `/tmp/n77.g6` nie istnieje (wynik jest już zastąpiony przez 73) |

Główny wniosek: **certyfikaty grafów są poprawne**. Słabości leżą w trzech miejscach:

- przegląd literatury i strategia (duża część mocy obliczeniowej poszła na cel, którego nie da się osiągnąć);
- odtwarzalność (narzędzia i dane leżą poza repo);
- język raportów („world record”, „exhaustive”, „unique”, „exact floor”), który opisuje wyniki heurystyczne jak dowody.

---

## 2. Co sprawdzono i jak

1. **Własny parser graph6 i analiza strukturalna** (`g6.py`): liczba wierzchołków i krawędzi, rozkład stopni, spójność, punkty artykulacji.
   - `n=370`: `m=555`, `{3:370}`, 0 punktów artykulacji ✔
   - `n=345`: `m=525`, `{3:330, 4:15}`, 0 punktów artykulacji ✔
   - `n=73`: `m=111`, `{3:70, 4:3}`, 0 punktów artykulacji ✔
2. **Niezależny dokładny licznik widma cykli** (`cyc.c`). Algorytm: kanoniczny start w najmniejszym wierzchołku i DFS z obcięciem odległością BFS w `G[≥s]`. Jest napisany od zera i różni się od MitM używanego w `verify-large`.
   - Kalibracja: Petersen daje 5:12, 6:10, 8:15, 9:20. Tutte–Coxeter daje 8:90, 10:72, 12:300. Obie zgodne z literaturą ✔
   - `n=370`: cykle o długościach {3,5,6,7,9…15} oraz **33, 34, …**. Nie ma żadnego cyklu o długości 16–32. Najkrótszy „podniesiony” cykl ma długość **33**, więc margin wynosi 1 (40 takich cykli).
   - `n=345`: ten sam obraz (924 cykle długości 33).
   - `n=73`: {3,5,6,7,17,18,…}. Nie ma C4/C8/C16 ✔
3. **`verify-large` uruchomiony jednowątkowo** (`--workers 1`): wynik ABSENT dla {4,8,16,32} na obu grafach f5 (0,40 s i 0,69 s). Zgodny z `cyc.c`. Raportowane 9,5–14,6 ms przy 16 wątkach są wiarygodne.
4. **Okna gadżetu H8*** (`h8.py`): S(0,1)={2..7}, S(0,2)=S(1,2)={3..7}, cykle wewnętrzne {3,5,6,7} ✔
5. **Wyczerpujące sprawdzenie rodziny Petersena** (`pet.c`): wszystkie podzbiory pozycji H8* × 3¹⁰ orientacji, w modelu minimów okien.

   | r (liczba H8*) | n | rozwiązania bez złych 5-cykli | minimalna liczba złych 5-cykli |
   |---:|---:|---:|---:|
   | 0 | 70 | 0 | **2** |
   | 1 | 71 | 0 | 2 |
   | 2 | 72 | 0 | 1 |
   | 3 | 73 | 4680 | 0 |

   Raport Track 2 (`n=72`: 0 rozwiązań; `n=73`: istnieje rozwiązanie) jest poprawny.
6. **Rachunek dla Tutte–Coxetera**: ręcznie odtworzono `E[excess] = 16(2a−30)/90` oraz `4(a−10)/15`. Uśrednianie jest dokładne, bo graf TC jest łukowo-przechodni, więc każda para krawędzi przy wierzchołku leży w 8 ośmiocyklach. Wyprowadzone progi `a ≥ 18` (kubiczne) i `a ≥ 14` (z H8*) są poprawne **wewnątrz tej rodziny**. Arytmetyka rzędów (`240 + 7a`, `15a + 7c`) się zgadza.

---

## 3. Słabe miejsca i błędy (od najważniejszych)

### 3.1 [KRYTYCZNE, strategia] Kampanie kubiczne `n < 78` szukały obiektu, który według literatury nie istnieje

A. V. Ripatti, *Faster approach for exhaustive search over graphs with certain properties* (BAIKAL 2017, abstrakt): *„computationally show that the smallest cubic graphs without 4,8,16 cycles have 78 vertices”*. Praca podaje też, że takich grafów jest 6 (graf Exoo i 5 innych). Metoda to generacja izomorficznie wolna w stylu McKaya/Brinkmanna (`minibaum`).

W repozytorium **nie ma żadnej wzmianki** o tym wyniku (`grep Ripatti|Baikal` → 0). Tymczasem:

- Wave D1, kampania 1h (`n=60,62,64`, 34,78 mld liści), Wave E (część kubiczna) i kampania 2h (`n=76,74,70` kubiczne, 42,63 mld liści) szukały kubicznego grafu {4,8,16}-free o `n < 78`. W sumie raporty deklarują ~83 mld liści LNS, czyli kilka godzin pracy całej 16-rdzeniowej maszyny.
- Część lifów napięciowych z Wave D2 przy `n=72` (kubiczne) dotyczy tego samego, niemożliwego zakresu.
- Wnioski oparte na tej błędnej ramie:
  - *„f(4) lies near the upper half of the open window [54, 78]”* (1h): dla grafów kubicznych to okno jest zamknięte. Pochodzenie dolnej granicy 54 nie jest nigdzie uzasadnione.
  - *„just 3 sixteen-cycles shy of breaking Exoo's f_cubic(4) ≤ 78”* (Wave E): liczba C16 nie jest miarą odległości od rozwiązania, a samo rozwiązanie nie istnieje.
  - „rock-solid empirical floor `C16 = 23`”, „deep confirmation of the `C16 = 3` floor”: to lokalne minima heurystyki, bez znaczenia dowodowego.

Zastrzeżenie: Ripatti to abstrakt konferencyjny, a słowa „probabilistic checking of every node” wymagają sprawdzenia, czy końcowa weryfikacja była dokładna. Wynik powinien jednak zostać uwzględniony **przed** uruchomieniem kampanii. Wniosek pozytywny: `f_{δ≥3}(4) ≤ 73 < 78` oznacza, że (o ile Ripatti ma rację) **optimum dla δ≥3 jest ściśle mniejsze niż optimum kubiczne**. Ten fakt warto wyeksponować zamiast „rekordów C16”.

**Rekomendacja**:

- dopisać Ripattiego do `docs/00_RESEARCH_STATUS.md`;
- przerwać i nie wznawiać kampanii kubicznych `n < 78` dla {4,8,16};
- przenieść budżet na δ≥3 (`n ≤ 72`) oraz na f(5).

### 3.2 [WYSOKIE, odtwarzalność] Narzędzia i dane leżą poza repozytorium

Wszystkie poniższe istnieją wyłącznie w katalogu roboczym innego agenta, `~/.gemini/antigravity-cli/brain/560c9e05-…/scratch/` (nie są śledzone przez git):

- poszukiwacze gadżetów `f5_gadget_hunter.cpp` i `f5_multideg4_gadgets.cpp`;
- solver okien/CSP `f5_window_solver.cpp`;
- PAWS/WalkSAT `f5_paws_frontier.cpp`;
- „niezależny weryfikator C++” `sglab_cyclecheck_large.cpp`;
- skrypty budujące certyfikaty (`track2_*.py`, `test_h8star_petersen_f4.py`);
- skrypty Wave E (`exp11_*.py`);
- surowe JSON-y kampanii (`campaign_1h_lns_60_62_64.json` itd.).

Konsekwencje:

- Raport Track 2 nazywa `sglab-cyclecheck-large` „Independent Verification Authority”, ale tego kodu nie da się przejrzeć z poziomu repo.
- Świadek `f_{δ≥3}(4) ≤ 77` (Wave E) nie ma certyfikatu w `docs/reports/certificates/`, a raport odsyła do `/tmp/n77.g6`, który nie istnieje.
- Narusza to misję projektu z AGENTS.md (*„reproducible”*, *„raw scientific history is preserved”*). Cała praca toczyła się poza runtime kampanii, Directorem i SQLite, więc nie ma trwałych rekordów kampanii.

**Rekomendacja**: zaimportować źródła do `cpp/` lub `tools/` (z testem), dołączyć certyfikat `n=77` i `n=74`/`C16=3` (jeśli mają wartość dowodową) oraz surowe JSON-y (albo ich hashe i lokalizację archiwum).

### 3.3 [WYSOKIE, poprawność wniosków] „Unique” i „0 found” pochodzą z próbkowania losowego, a nie z wyczerpującego przeszukania

`f5_gadget_hunter.cpp` i `f5_multideg4_gadgets.cpp` losują pary „stubów” (configuration model, `std::shuffle` + `mt19937_64`) i zliczają „trials”. Na tej podstawie raport twierdzi:

- dla `n=7` są „exactly two” gadżety;
- dla `n=9,11,13` istnieje „**0** {C4,C8,C16}-free gadgets”;
- `H15` to „unique window type”;
- w statusie: H8* to „**unique** … 8-vertex 3-port gadget”, podczas gdy raport Track 2 mówi „**TWO** sporadic types” (niespójność).

Próbkowanie konfiguracyjne jest niejednorodne względem klas izomorfizmu, a rzadkie grafy mogą nie wypaść nawet przy 10⁷ prób. Żadne z tych zdań nie jest twierdzeniem. Wariant non-cubic obejmował przy tym tylko wybrane sekwencje stopni (porty stopnia 2, 1–3 wewnętrzne wierzchołki stopnia 4).

**Rekomendacja**: wyczerpująca generacja (`nauty geng` z ograniczeniami stopni lub dedykowany generator) dla `n ≤ 13` jest tania i zamieniłaby te zdania w fakty. Do tego czasu w raportach należy pisać „nie znaleziono w N próbach”.

### 3.4 [ŚREDNIE, błąd matematyczny] Fałszywy „pigeonhole floor” w Wave E

Wave E: *„40/12 = 3.333 > 3, at least 4 five-cycles carry ≥ 4 port-0 incidences … proving C16 ≥ 4 is exact”*.

- Z sumy 40 przy maksimum 5 na cykl wynika tylko `40 ≤ 3(12−B) + 5B`, czyli **B ≥ 2**, a nie B ≥ 4.
- Wyczerpujące sprawdzenie (`pet.c`, r=0) daje **minimum 2 złe 5-cykle**, a nie 4. Teza „exact floor C16 ≥ 4” nie ma więc dowodu. Może być prawdziwa, jeśli każdy zły 5-cykl generuje ≥ 2 szesnastocykle, ale tego nie wykazano.
- Kampania 2h powtarza ten argument („consistent with the exact `Petersen + 10·H7` pigeonhole floor”).

### 3.5 [ŚREDNIE, atrybucja] `f_cubic(6) ≤ 30 360`

- Rozumowanie jest poprawne. Na cyklu bazowym długości L ≥ 17 leży ≤ ⌊L/5⌋ kopii H7, więc długość cyklu wynosi ≥ 4L − ⌊L/5⌋ ≥ 65. Cykle wewnętrzne gadżetów mają ≤ 15 i nie są potęgami 2. Pakowanie maksymalne spełnia |P| ≥ ⌈2048/46⌉ = 45.
- Ale:
  - **„Previous Published Best 30 720” nie jest wartością opublikowaną.** Abstrakt Garcíi podaje `f(6) ≤ 32 640` (= 15 · 2176). 30 720 to złożenie twierdzenia Garcíi z wynikiem `n(3,17) ≤ 2048`.
  - Wynik `n(3,17) ≤ 2048` pochodzi z Exoo, Goedgebeur i in., arXiv:2511.07247 (listopad 2025, EJC v33i3p48), a nie z „July 2026”, jak twierdzi raport.
  - Bound jest **warunkowy** (graf 2048 nie jest w repo), nie ma artefaktu i nie jest „certyfikowany”.
  - Poprawa wynosi 1,2% i jest łatwa do pogłębienia: wiążą tylko cykle bazowe długości 17…21 (dla L ≥ 22 warunek 4L − h ≥ 65 zachodzi dla każdego h ≤ L). Maksymalne 4-pakowanie to bardzo zgrubna konstrukcja, a dla δ≥3 można też użyć H8*.

### 3.6 [ŚREDNIE, język i interpretacja] Przesadne sformułowania

- **„World records” i „-23.3%” dla `f_{δ≥3}(5)`.** Porównanie dotyczy bound'u kubicznego (450). Nie wiadomo, czy istnieje osobny opublikowany bound dla δ≥3. Statusu literatury nie zweryfikowano poza abstraktem Garcíi (np. czy biblioteka gadżetów Garcíi zawiera gadżety niekubiczne).
- **„Exact Phase Boundaries”, „mathematically impossible (a ≤ 13)”.** To prawda tylko wewnątrz jednej rodziny: baza TC, gadżety {H15, H8*, H7} i model minimów okien. Nie wynika z tego żadne ograniczenie dolne na f(5).
- **„`a = 19` (n=362): min_viol = 5”, „n=344: min_viol=3”** to wyniki WalkSAT/PAWS, czyli heurystyki. Instancja jest malutka (30 pozycji × typ × 3 orientacje, 162 cykle bazowe), więc **SAT/ILP rozstrzygnąłby ją dokładnie w sekundy**. Pozostawienie `n = 354…362` jako „nierozwiązane heurystycznie” to stracona okazja na kolejną poprawę albo na pełny dowód optymalności w rodzinie.
- **„Triple-certified”**: jeden z trzech weryfikatorów (C++ large) jest poza repo, a M4 (`cpp/sglab_cyclecheck.cpp`) obsługuje tylko `n ≤ 128`. Dla `n=345/370` M4 w ogóle nie brał udziału. Niezmiennik 3 nie zostaje naruszony, bo to nie są kontrprzykłady, ale słowo „certified” bez M4 jest niekonsekwentne z resztą projektu.
- **Daty**: plik nazywa się `…_2026_11_27.md`, a commit pochodzi z 2026-11-26 21:33Z.

### 3.7 [ŚREDNIE, kod] `rust/sglab-engine/src/large_verify.rs` (`verify-large`)

Algorytm jest **poprawny**. Kanoniczny start s = min, wszystkie ścieżki długości h do t przez wierzchołki > s, pary o rozłącznym wnętrzu w kubełku t to bijekcja z 2h-cyklami (h ≥ 2). Brak obcięcia nie psuje dokładności. Uwagi:

1. **Martwy kod i mylący komentarz.** Odległości BFS (`dist`) są liczone, ale `dfs_half` ich nie używa. Komentarz twierdzi, że stosowane jest obcięcie `dist_gt_s[v] <= h`. Dokładność to zachowuje, ale dokumentacja kłamie, a liczba wyliczanych ścieżek jest pełna (dla C32 rzędu 3·2¹⁵ na start).
2. **Świadek sprawdzany tylko przez `debug_assert`.** W buildzie release cykl FOUND nie jest weryfikowany krawędź po krawędzi.
3. **`--lengths` po cichu pomija niepoprawne tokeny** (`filter_map(...ok())`). Literówka typu `4,8,16,3 2` zweryfikuje mniej długości bez błędu. Nieparzysta długość kończy się `assert!` (panic) zamiast błędu CLI. `from_graph6` nie odrzuca nadmiarowych bajtów.
4. **Testy**: jeden test na Markström-24 (`n=24`) obejmuje tylko pierwsze słowo maski `[u64; 8]`. Nie ma testu dla `n > 64` (słowa 1–7), ani dla grafu z obecnym C32, ani porównania z referencyjnym DFS dla `n ∈ (128, 512]`, czyli dokładnie zakresu, dla którego narzędzie powstało. Dla obu certyfikatów lukę zamyka mój niezależny `cyc.c`, ale regresje w przyszłości pozostaną niewykryte.

### 3.8 [NISKIE] Wave D2

- **Niespójna tabela.** Sito Björklunda C32 miało być wołane tylko dla kandydatów `C4=C8=C16=0`, a wiersze `k33 × A4` itd. mają 0 takich kandydatów i jednocześnie wynik sita „FOUND”. Najwyraźniej sito szło po kandydatach `C4=C8=0`. Opis albo tabelę trzeba poprawić.
- Sito jest **Monte Carlo** (fałszywe negatywy ≤ 5,2·10⁻⁷). Nadaje się do FOUND, ale nie wolno go używać do orzekania ABSENT. Obecnie tak nie jest używane, ale warto to zapisać jako regułę.
- Cytowania „Burkhart Nov 2026” i „Zhuge n ≤ 68” nie zostały zweryfikowane. Należy podać identyfikatory arXiv.

### 3.9 [NISKIE, proces] Obowiązki dokumentacyjne z AGENTS.md

- Nowe podkomendy CLI (`verify-large`, `lns-polish --rrt-slack/--bipartite`, `voltage-search`, `bjorklund-c32`) są opisane wyłącznie w `IMPLEMENTATION_STATUS.md`. Brakuje dokumentacji referencyjnej i architektonicznej oraz ADR dla nowej, trwałej ścieżki weryfikacji `n ≤ 512`.
- Na ~5 000 nowych linii Rusta (D1–F) przypada 9 testów jednostkowych (`large_verify` 1, `lns` 1, `voltage_bipartite` 2, `cycles` 5).

---

## 4. Wątpliwości decyzyjne

1. **Kolejność „najpierw moc obliczeniowa, potem literatura”.** Kilka godzin 16-rdzeniowych kampanii poszło na problem rozstrzygnięty w 2017. Tani krok, przegląd literatury, powinien poprzedzać każdą kampanię „record hunt”.
2. **Minimalizacja liczby C16 jako funkcja celu.** Ten sygnał nie przekłada się na wykonalność. Bardziej obiecujące są metody dokładne na małych przestrzeniach strukturalnych (gadżety × orientacje × baza), co Track 2 pokazał w praktyce: rekordy padły w milisekundach dzięki CSP, a nie dzięki dziesiątkom miliardów liści LNS.
3. **Heurystyki (WalkSAT/PAWS) tam, gdzie wystarczy solver dokładny.** Dotyczy to `n=362`, `n=354`, `n=344`, `n=338` w rodzinie TC. Jeden przebieg SAT/ILP w każdym z tych przypadków albo poprawi rekord, albo da twierdzenie „optymalne w rodzinie”.
4. **Wybór bazy.** Rozważano tylko TC (f5) i Petersena (f4). Inne bazy o talii 8/10 (Heawood × lift, grafy klatkowe, lify napięciowe) oraz mieszanki gadżetów (w tym H8* w kubicznej wersji, jeśli istnieje) nie zostały przeszukane w sposób dokładny.
5. **Praca poza runtime projektu.** Wyniki nie przeszły przez kampanie, Directora ani SQLite, więc nie mają audytowalnej historii, której projekt wymaga w swoich niezmiennikach.

---

## 5. Zalecane następne kroki (w kolejności)

1. Zaimportować do repo źródła Track 2 i Wave E oraz brakujące certyfikaty (`n=77`, ewentualnie `n=74`/`n=76` jako „near-miss”) i surowe JSON-y.
2. Dodać do `docs/00_RESEARCH_STATUS.md` Ripattiego 2017, Garcíę 2609.04686 (f(6) ≤ 32 640) i Exoo et al. 2511.07247 (n(3,17) ≤ 2048). Opisać status `f_cubic(4) = 78` (computationally).
3. Erratum (nowym plikiem, bez przepisywania starych raportów): pigeonhole z Wave E, „unique/0 found” jako wyniki próbkowania, atrybucja 30 720, niespójność H8* „unique” vs „two types”, niespójność tabeli D2.
4. `large_verify.rs`:
   - użyć `dist` do obcięcia albo usunąć BFS i poprawić komentarz;
   - weryfikować świadka w release;
   - twardy błąd dla złych `--lengths`;
   - testy dla `n ∈ {100, 300, 512}` z porównaniem do referencyjnego DFS (np. `cyc.c`) i z grafem, w którym C32 występuje.
5. Gdy maszyna będzie wolna: dokładny SAT/ILP dla rodziny TC (`a = 18, 19` kubicznie; `n = 338…344` dla δ≥3) oraz wyczerpująca generacja gadżetów `n ≤ 13` (`geng`).

---

## 6. Odtworzenie weryfikacji z tego przeglądu

```bash
D=docs/reports/assets/review-2026-11-26; W=$(mktemp -d); cp $D/* $W; cd $W
python3 g6.py ~/DEV/heg/docs/reports/certificates/*.g6     # stopnie, spójność, punkty artykulacji; zapisuje *.el
gcc -O2 -o cyc cyc.c && ./cyc f5_cubic_n370_TC_20H15_10H7.g6.el 34   # ~5 s, 1 wątek
python3 h8.py && gcc -O2 -o pet pet.c && ./pet                       # okna H8*, rodzina Petersena r=0..3
```

## Źródła zewnętrzne (sprawdzone tylko na poziomie abstraktu)

- A. V. Ripatti, *Faster approach for exhaustive search over graphs with certain properties*, BAIKAL 2017: https://isem.irk.ru/conferences/mopt2017/Abstracts/BAIKAL_2017_paper_138.pdf
- D. Garcia, *Small graphs without power-of-two cycles…*, arXiv:2609.04686: https://arxiv.org/abs/2609.04686
- G. Exoo, *Three graphs and the Erdős–Gyárfás conjecture*, arXiv:1403.5636: https://arxiv.org/abs/1403.5636
- Exoo, Goedgebeur et al., *New small regular graphs of given girth…*, arXiv:2511.07247: https://arxiv.org/abs/2511.07247
