# Hipoteza Erdősa–Gyárfása: niezależna weryfikacja stanu wiedzy (XI 2026) i nowe projekty obliczeniowe dla silnika `heg`

Najważniejszy wniosek: najbardziej obiecującym nowym projektem dla Twojego serwera nie jest dalsze szukanie kontrprzykładu dla n ≤ 64, bo ten zakres jest już w dużej mierze wykluczony (ogólne n ≤ 40, kubiczne n ≤ 48, dwudzielne n ≤ 66).\[1\] Jest nim **„ściśnięcie” funkcji ekstremalnej f(4)**, czyli najmniejszego rzędu grafu kubicznego bez C4, C8 i C16.\[2\] Obecnie wiadomo tylko 54 ≤ f(4) ≤ 78, przy czym dolne ograniczenie pochodzi z **nieopublikowanego** obliczenia Markströma.\[3\] Ten problem idealnie pasuje do architektury Twojego silnika (n = 54…76, plateau C16), ma jasną wartość publikacyjną i obie strony (heurystyczna górna, dokładna dolna) da się atakować równolegle.

## TL;DR

- **Weryfikacja:** główne twierdzenia poprzedniego raportu o pracach z 2026 r. potwierdzają się w źródłach pierwotnych (Ducoffe–Dumitru arXiv:2609.28594, Tranquilli arXiv:2608.02675, Garcia arXiv:2609.04686, Culus arXiv:2610.26403, Burkhart arXiv:2611.05060). Są jednak istotne korekty. Carr (arXiv:2605.22844) dowodzi frakcji 4/7, a nie > 2/3; poprawa do > 2/3 + 1 pochodzi od Ducoffe–Dumitru. Ducoffe–Dumitru **nie generowali certyfikatów dowodowych** („The solver was not asked to produce a resolution proof”). f(k) u Garcii dotyczy grafów **kubicznych**.
- **Nowe od poprzedniego raportu:** preprint Zenodo K. Henry'ego z 3.11.2026 (f(5) ≤ 370, f(6) ≤ 10 522 warunkowo). Wydanie Exoo i in. w EJC 33(3) #P3.48 (2026). „Smart cubing” dla SMS (Kirchweger–Xia–Peitl–Szeider, CP 2026, LIPIcs 379: „The prerun and cubing phase alone provides a speedup between 2x and 3x compared to standard SMS”). Liczności kubicznych grafów talii ≥ 9 z House of Graphs (18, 474, 27 169, 1 408 813 dla n = 58…64). Fakt, że wszystkie trzy (3,10)-klatki (70 wierzchołków: Balaban 10-cage, graf Harriesa, graf Harriesa–Wonga) są dwudzielne. Do tego szereg nieformalnych repozytoriów (mcolsen, Gebendorfer, gsidoine).
- **Rekomendacja:** uruchom równolegle trzy szybkie projekty: (1) sprawdzenie wszystkich kubicznych grafów talii ≥ 9 dla n = 58…64 (minuty) i dalej do n = 66–70; (2) domknięcie przypadku kubicznego dwudzielnego n = 70 (3 klatki + rozszerzenie wyszukiwania Tranquilli/Zhuge do 35 punktów); (3) dwustronny atak na f(4). Do silnika dodaj tryb „prefiksu {4,8,16}”, wyrocznię C16 z przyrostowym MitM 7+7 oraz tryb dokładny z kanoniczną augmentacją i strumieniami certyfikatów.

## 1. Weryfikacja kluczowych twierdzeń poprzedniego raportu

Legenda statusu: **R** = recenzowane, **P** = preprint arXiv, **Z** = Zenodo (bez recenzji), **N** = nieformalne (GitHub/ResearchGate/fora).

| Twierdzenie poprzedniego raportu | Werdykt | Zweryfikowane metadane i treść |
|---|---|---|
| Ducoffe–Dumitru, arXiv:2609.28594 | **Potwierdzone, z korektami** | G. Ducoffe, B. Dumitru, „Towards a more structured search for Erdős-Gyárfás counter-examples”, v1 23.09.2026 (P), tylko v1. Tw. 5.1: n ≤ 40 (ogólne), dwudzielne n ≤ 66, kubiczne n ≤ 48.\[1\]\[4\] Lemat 2.1, Tw. 2.3 (dla nieparzystego n: jedyny wierzchołek cięcia stopnia 4, dwie równe, 2-zdegenerowane części), Wn. 2.4 (parzyste n ⇒ dwuspójność), Tw. 3.3 (m ≤ 2n − 2), Tw. 3.7 (ℓ ≥ 2n/3 + 1), Lemat 3.5 i Tw. 3.8 (brak 2^j-podziałów multigrafów o δ ≥ 3), Hip. 4.1 ⇔ EGC (Tw. 4.2) oraz **Tw. 4.4: wersja „tęczowa” ⇔ EGC dla dwudzielnych**. Kodowania E0–E5 potwierdzone. Łącznie „about 30 core-days”. **Brak certyfikatów DRAT.**\[2\] Repozytorium kodu jest wzmiankowane w przypisie; nazwy `bogdan27182/eg-paper` nie zweryfikowałem. |
| „Statyczne C4 + leniwe C8/C16/C32 najlepsze” | **Częściowo** | Dla kubicznych E5 (C4 w CNF + spójność) jest szybsze od E4 (n = 44: 32 640,9 s vs 60 028,7 s). Najsilniejszy efekt ma jednak **częstotliwość propagatora**: przy n = 29 (E2) czas spada z 1110,5 s (k = 30) do 106,4 s (k = 5). Statyczna dwuspójność: +41–62% czasu.\[2\] |
| Carr, arXiv:2605.22844 | **Różni się** | A. Carr, „Every Minimal Counterexample to the Erdős-Gyárfás Conjecture is Predominantly Cubic”, 13.05.2026 (P). Wierzchołki stopnia ≥ 4 tworzą zbiór niezależny (obserwacja Markströma), każdy wierzchołek ma sąsiada stopnia 3 i **co najmniej 4/7** wierzchołków ma stopień 3.\[5\]\[6\] Frakcja > 2/3 to wynik Ducoffe–Dumitru.\[1\]\[7\] |
| Carr, arXiv:2508.19302 (średnica 2 ⇒ C4 lub C8) | Potwierdzone (P)\[8\] | Daty v1/v2 według MathWorld: 30.01.2026 dla wersji cytowanej.\[7\] „Przyjęte do BICA” – **nie zweryfikowano**. |
| Garcia, arXiv:2609.04686 | **Potwierdzone, z doprecyzowaniem** | D. Garcia, 4.09.2026 (P). n ≤ 23 ⇒ C4 lub C8 (CEGAR + CaDiCaL 1.9.5, DRAT/drat-trim, n = 23 ≈ 5850 s). Lemat Exoo dla G450 fałszywy, konstrukcja naprawiona (f(5) ≤ 450). f(k) ≤ 15·n₃(2^{k−2}+1), f(6) ≤ 32 640. 78 optymalne wśród gadżetów na bazach ≤ 12 wierzchołków.\[9\] **f(k) jest zdefiniowane dla grafów kubicznych**, a stan wiedzy to „54 ≤ f(4) ≤ 78, the lower bound being an unpublished computation of Markström”.\[3\]\[9\] Artefakty: doi:10.5281/zenodo.22180583.\[9\] |
| Balaji, Zenodo 10.5281/zenodo.21190438 | Potwierdzone (Z/N) | Cytowane przez Ducoffe–Dumitru jako n ≤ 31.\[2\] Uwaga: opis repozytorium mówi „≤30 vertices”, a tabela sięga n = 31; drobna niespójność.\[10\] |
| Tranquilli, arXiv:2608.02675 | Potwierdzone (P) | J. Tranquilli, „A 60-Vertex Lower Bound for Cubic Bipartite Counterexamples…”, 2.08.2026. Każdy kubiczny dwudzielny graf na ≤ 58 wierzchołkach ma C4, C8 lub C16.\[11\]\[12\] Metoda: lemat Moore'a (< 62 wierzchołki ⇒ C6), grafy Leviego konfiguracji v₃, dwie orbity korzeni, wyszukiwanie do 29 punktów, dwie niezależne wyrocznie C16 (DFS oraz łączenie 7-krawędziowych półścieżek), strumienie certyfikatów.\[11\]\[12\] Zenodo 10.5281/zenodo.21695513. Praca wspomagana przez ChatGPT/Codex (ujawnione).\[13\] |
| Zhuge, Zenodo 10.5281/zenodo.21981786 | Potwierdzone (Z) | Y. Zhuge, artefakt „A 70-Vertex Lower Bound…”: kubiczne dwudzielne ≤ 68 ⇒ C4/C8/C16, wyszukiwanie z limitem 34 punktów, oparte na kodzie Tranquilliego (commit 67adc92d).\[14\] Brak recenzji. |
| Culus, arXiv:2610.26403 | Potwierdzone (P) | J.-F. Culus, 19.10.2026: 3-spójne kubiczne grafy w płaszczyźnie rzutowej z fw ≥ 3 i **ew ≥ 48** mają kontraktowalny cykl 2^m, 2 ≤ m ≤ 7. Pytanie 4.1 (małe ew) otwarte.\[15\] |
| Burkhart, arXiv:2611.05060 | Potwierdzone (P) | M. C. Burkhart, 3.11.2026: Cayley grup **nieparzystego rzędu** (|S| ≥ 3) oraz (wniosek) grup nilpotentnych.\[16\]\[17\] Uwaga praktyczna: grafy kubiczne mają parzysty rząd, więc część „nieparzysta” **nie dotyczy grafów kubicznych**. |
| Liu–Montgomery | Potwierdzone (R) | JAMS 36 (2023) 1191–1234, doi:10.1090/jams/1018.\[15\] ID arXiv z poprzedniego raportu nie sprawdzono. |
| Hu–Shen (P10-free) | Potwierdzone (R) | Discrete Math. 347(12):114175 (2024).\[13\] ID arXiv nie sprawdzono. |
| Hegde–Sandeep–Shashank | Potwierdzone (P) | arXiv:2410.22842 v2 (11.02.2025).\[18\] Według Tranquilliego daje „with computer assistance, P13-free graphs”.\[13\] |
| Exoo arXiv:1403.5636; Exoo–Goedgebeur–Jooken–Stubbe–Van den Eede | Potwierdzone | 1403.5636 (22.03.2014).\[19\] 2511.07247 ukazało się w **Electron. J. Combin. 33(3) #P3.48 (2026), DOI 10.37236/14834** (R).\[20\] |
| Zenodo 10.5281/zenodo.22019344 („pełny dowód”) | **Nie sprawdzono** | Nie dotarłem do rekordu. Traktować jako niezweryfikowane. |
| Gebendorfer (ResearchGate) | Częściowo (N) | Preprint z 8.09.2026: kubiczne dwudzielne grafy wierzchołkowo-przechodnie **talii 6** mają cykl 2^k. Zgłoszony jako issue #7281 w google-deepmind/formal-conjectures.\[21\]\[22\] Wariantu „talia 12” **nie znaleziono**. |
| MathWorld | Potwierdzone, data nie | Hasło cytuje Burkharta i Bloom „Oct. 1, 2026”.\[7\] Dokładnej daty 25.11.2026 nie zweryfikowano. |
| ProofAtlas, issues grandchallenge | Nie sprawdzono | — |

## 2. Nowe źródła i wyniki nieobecne w poprzednim raporcie

**Prace i artefakty bezpośrednio o EGC:**

1. **K. Henry, „Improved cubic graph constructions avoiding power-of-two cycle lengths”, Zenodo 10.5281/zenodo.23886386, opublikowane 3.11.2026 (Z, bez recenzji).** Jawny spójny graf kubiczny na **370 wierzchołkach** bez C4, C8, C16, C32 ⇒ **f(5) ≤ 370** (poprawa 450).\[23\] Ogólnie f(k) ≤ 15·n₃(2^{k−2}) dla k ≥ 4 i f(k) ≤ 15·n₃(2^{k−2}) − 8 dla k ≥ 5 (zamiana jednego 15-wierzchołkowego gadżetu na 7-wierzchołkowy). Stąd **f(6) ≤ 10 522**, ale tylko przy założeniu istnienia „reported 702-vertex cubic graph of girth 16”, którego autor nie zrekonstruował.\[23\] Uwaga: Garcia pisze n₃(2^{k−2}+1), a Henry n₃(2^{k−2}); tę rozbieżność trzeba sprawdzić w pełnym tekście przed cytowaniem.\[3\]\[23\]
2. **mcolsen/erdos-gyarfas (N, GitHub, VII–VIII 2026, praca wspomagana przez Claude/GPT, autor sam pisze „I have not reviewed the findings”).**\[24\] Deklaruje „Smallest cubic graph with no C₄/C₈/C₁₆ has between 50 and 82 vertices”.\[24\] Jest to **sprzeczne** z f(4) ≤ 78 (Exoo), więc wynik ma niską wiarygodność, ale pokazuje, że problem f(4) jest „w powietrzu”.\[3\]
3. **Gebendorfer, issue #7281 w google-deepmind/formal-conjectures (N):** opiera się na klasyfikacji kubicznych grafów wierzchołkowo-przechodnich talii 6 (Potočnik–Vidali).\[21\] Analogiczna klasyfikacja dla **talii 7** istnieje: M. Lekše, M. Toledo, arXiv:2508.19880 (P).\[25\] To otwiera teoretyczno-obliczeniową drogę do „EGC dla wszystkich kubicznych VT grafów talii ≤ 7”.
4. **the-omega-institute/trureturing issue #14778 (N, 9.10.2026):** próba dowodu hipotezy Ducoffe–Dumitru, że minimalny dwudzielny kontrprzykład jest 2-krawędziowo spójny. Stan na 9.10: „no later settlement found”.\[4\]
5. **gsidoine/rewriting-graph-conjectures PR #13 (N, 28.10.2026):** „exact three-edge-cut simple-cycle generating-polynomial identity” i rachunek zmiany defektu przy wymianie „brzegu” cięcia 3-krawędziowego, z udokumentowaną obstrukcją dla grafu Petersena.\[26\] Sam rachunek jest interesujący jako operator dla Twojego silnika (sekcja 6), ale wymaga własnej weryfikacji.
6. Inne nieformalne kampanie (d3lefts „Lemnis” – wykluczenia nakryć regularnych K4; adamben04/solved-conjectures – nakrycia abelowe podzielonego czworościanu, przykład 95-wierzchołkowy; Drill23/erdos-64-lean4 z deklaracją |V₃| ≥ 12n/17; FragileTech/hypostructure z rzekomym manuskryptem dowodu).\[27\]\[28\]\[29\]\[30\] **Żadnej z tych deklaracji nie zweryfikowałem** i nie należy ich cytować jako wyników.

**Uwaga terminologiczna (pułapka przy przeszukiwaniu):** arXiv:2610.24484 („Erdős-Gyárfás Balanced Five-Colorings”, Xia–Szeider) i arXiv:2607.21915 (pokrycia ścieżkami monochromatycznymi) dotyczą **innych** hipotez Erdősa–Gyárfása.\[31\]\[32\]

**Narzędzia i dane spoza niszy, bezpośrednio użyteczne:**

- **Kirchweger, Xia, Peitl, Szeider, „Smart Cubing for Graph Search: A Comparative Study”, arXiv:2501.17201 (27.01.2025); CP 2026, LIPIcs vol. 379, 33:1–33:19, DOI 10.4230/LIPIcs.CP.2026.33 (R).** Cube-and-conquer dla SMS z propagatorami: „The prerun and cubing phase alone provides a speedup between 2x and 3x compared to standard SMS”, a strojenie parametrów daje dodatkowe 1,5–2× na trudniejszych instancjach. Testowano m.in. kolorowanie grafów bez trójkątów, Kochen–Specker i grafy krytyczne o średnicy 2. To brakujący element, żeby obliczenia klasy D–D (n = 40 ≈ 61 h na jednym rdzeniu) rozłożyć na wiele rdzeni.
- **T. Zhang, S. Szeider, „The 3-Decomposition Conjecture: A SAT-Based Approach with Specialized Propagators”, CP 2025, LIPIcs vol. 340, 39:1–39:19, DOI 10.4230/LIPIcs.CP.2025.39 (R):** dynamiczne zakazywanie częściowych podgrafów odkrywanych w trakcie wyszukiwania (Glasgow Subgraph Solver), wprost dla „minimalnych kontrprzykładów” i konfiguracji redukowalnych; autorzy „verify the conjecture for all relevant graphs up to 28 vertices”. To gotowy wzorzec do automatycznego odkrywania konfiguracji redukowalnych dla EGC.
- **House of Graphs, tabela grafów kubicznych:** talia ≥ 9: n = 58 → 18, 60 → 474, 62 → 27 169, 64 → 1 408 813 (60–64 według McKay–Myrvold–Nadon, niezależnie potwierdzone tylko dla 58). Talia ≥ 8: 40 → 155, 42 → 4337, 44 → 266 362, 46 → 20 807 688. Talia ≥ 7: n = 40 → 220 323 447 962.\[33\]
- **(3,10)-klatki:** są dokładnie trzy (Balaban 10-cage, graf Harriesa, graf Harriesa–Wonga), wszystkie dwudzielne i 70-wierzchołkowe. Minimalność 70 wykazali O'Keefe i Wong (JCTB 29 (1980) 91–105), a kompletność listy P. K. Wong (Discrete Math., 1983): „it is shown that these are the only three possible (3, 10)-cages”. (3,9)-klatek jest 18 (Brinkmann–McKay–Saager).
- **Census Potočnik–Spiga–Verret** („Cubic vertex-transitive graphs on up to 1280 vertices”, J. Symbolic Comput. 50 (2013) 465–477, DOI 10.1016/j.jsc.2012.09.002): według MathWorld „containing 111,360 nonisomorphic graphs”, czyli spójnych kubicznych grafów wierzchołkowo-przechodnich do 1280 wierzchołków (dane: Zenodo 10.5281/zenodo.6576526). Certyfikaty grup automorfizmów dla 111 674 grafów (PSV + census symetrycznych Condera do 2048), Zenodo 10.5281/zenodo.19560683.\[34\]
- **PatternBoost** (Charton–Ellenberg–Wagner–Williamson, arXiv:2411.00566) i **AlphaEvolve** (Georgiev–Gómez-Serrano–Tao–Wagner, arXiv:2511.02864, 67 problemów).\[35\]\[36\] Twój ekosystem już zawiera analog (mutation-forge-lab: LLM-ewolucja polityk mutacji), więc to nie jest nowa rekomendacja, tylko punkt odniesienia.\[37\]

## 3. Zaktualizowana tabela granic obliczeniowych (stan na 27.11.2026)

| Klasa | Najwyższe zweryfikowane n | Źródło i status | Uwagi |
|---|---|---|---|
| Ogólne, δ ≥ 3 | **40** | Ducoffe–Dumitru (P),\[1\] SMS + CaDiCaL + GSS, bez certyfikatów\[1\]\[2\] | n ≤ 31: Balaji (Z). n ≤ 23 z silniejszą tezą „C4 lub C8”: Garcia (P, DRAT)\[9\]\[10\] |
| Dwudzielne, δ ≥ 3 | **66** | Ducoffe–Dumitru (P) | n = 66: 202 884,8 s na rdzeń\[2\] |
| Kubiczne | **48** | Ducoffe–Dumitru (P) | n = 48: 325 809,2 s (E4)\[2\] |
| Kubiczne dwudzielne | **58** (certyfikowane) / **68** (Zenodo) | Tranquilli (P) / Zhuge (Z)\[12\] | Teza silniejsza: zawsze C4, C8 lub C16\[12\]\[13\]\[14\] |
| Kubiczne, talia ≥ 5 / ≥ 6 / ≥ 7 | 48 (dziedziczone) | brak osobnych prac | Snarkhunter dla talii ≥ 7 przy n = 40 to już 2,2·10¹¹ grafów, więc samo wyliczanie nie przebije 48\[33\] |
| Kubiczne, talia ≥ 8 | **trywialnie 56**; 58–64 nie sprawdzone publicznie | wniosek | Talia dokładnie 8 ⇒ C8. Talia ≥ 9 wymaga n ≥ 58. Katalogi 58–64 istnieją, ale **nie znalazłem publikacji sprawdzającej w nich C16/C32** |
| f(3) (kubiczne bez C4, C8) | = 24 | Markström; Garcia\[3\] | — |
| f(4) (kubiczne bez C4, C8, C16) | **54 ≤ f(4) ≤ 78** | dolne: Markström (nieopublikowane), górne: Exoo\[3\] | mcolsen (N) deklaruje 50–82; niespójne\[24\] |
| f(5) | ≤ 450 (P) / **≤ 370 (Z)** | Garcia / Henry | — |
| f(6) | ≤ 32 640 (P) / ≤ 10 522 (Z, warunkowo) | Garcia / Henry | — |

Wpływ redukcji strukturalnych 2024–2026: u Ducoffe–Dumitru E2 przyspiesza wobec E0 2,6× (n = 22) i 4,9× (n = 29), a E1 i E2 różnią się o ≤ 13% dla n = 33…40.\[2\] Oznacza to, że przesunięcie granicy z 31 do 40 zawdzięczamy głównie warunkom (R1), (R2) i (C1) oraz strojeniu propagatora, a nie najnowszym, „głębokim” lematom. Dwuspójności **nie** użyto w głównych przebiegach.\[2\]

## 4. Ranking nowych projektów obliczeniowych

### P1. „Ściśnięcie” f(4): dwustronny atak na najmniejszy kubiczny graf bez C4, C8, C16 — **najwyższy priorytet**

- **Cel:** (a) heurystycznie znaleźć kubiczny graf na < 78 wierzchołkach bez {C4, C8, C16}; (b) dokładnie podnieść dolne ograniczenie z nieopublikowanego 54 do opublikowanego i certyfikowanego ≥ 56–60.
- **Dlaczego otwarte:** Garcia (wrzesień 2026) wprost podaje 54 ≤ f(4) ≤ 78 z dolną granicą „unpublished”. Wykazał też, że 78 jest optymalne **tylko wśród konstrukcji gadżetowych na bazach ≤ 12 wierzchołków**, więc lepszy graf musi być „niegadżetowy” albo mieć większą bazę.\[3\] Wyszukiwania D–D dla kubicznych n ≤ 48 zakazują także C32, więc nie rozstrzygają f(4).
- **Redukcja na start (nowa obserwacja):** w kubicznym grafie bez C4 i C8 talia należy do {3, 5, 6, 7} albo jest ≥ 9; talie 4 i 8 są wykluczone z definicji. Talia ≥ 9 wymaga n ≥ 58.
- **Plan (a), heurystyka:** Twój silnik w trybie cubic-only z funkcją celu ograniczoną do prefiksu {4, 8, 16}, n = 54, 56, …, 76. Seedy: (3,9)-klatki (58 wierzchołków, 18 grafów) i grafy talii 9 dla n = 60–64 z House of Graphs (automatycznie bez C4 i C8, więc defekt zawiera wyłącznie C16). Do tego lifty napięciowe (generator z repozytorium AGT-Kulak/smallRegGirthGraphs, Exoo i in.).\[20\]\[38\]\[39\]
- **Plan (b), dokładnie:** SMS (lub własna kanoniczna augmentacja) z C4 w CNF, C8/C16 leniwie, częstotliwość propagatora 5, rozbicie przez smart cubing. Dla każdego n osobny przebieg ze strumieniem certyfikatów odrzuceń (świadek cyklu dla każdej odciętej gałęzi, jak u Tranquilliego).
- **Koszt:** (a) tygodnie CPU, bez wyraźnej granicy. (b) Ekstrapolacja z D–D (kubiczne n = 48 ≈ 90 h na rdzeń, ok. ×2 na każde +2 wierzchołki) daje ok. 4–8× tego dla n = 52–54 i dziesiątki dni-rdzeni dla n = 58. Dla 32–64 rdzeni to tygodnie. Uwaga: bez zakazu C32 przestrzeń może być większa, więc szacunek jest niepewny.
- **Rezultat i wartość:** każde z dwóch (nowy graf < 78 albo certyfikowane f(4) ≥ 56) jest samodzielnie publikowalną notą. Oba razem byłyby mocnym artykułem w EJC lub Discrete Math.
- **Ryzyko:** średnie. Jeśli f(4) = 78, część (a) nic nie da, ale (b) i tak przynosi wynik.
- **Walidacja:** odtworzenie f(3) = 24 i czterech grafów Markströma;\[3\] dla (b) zgodność liczności z nauty `geng`/`genreg` dla małych n przy wyłączonym C16.

### P2. EGC dla wszystkich kubicznych grafów talii ≥ 9 (i ≥ 8) dla n ≤ 64, potem 66–70 — **szybka wygrana**

- **Cel:** twierdzenie „każdy kubiczny graf talii ≥ 8 na ≤ 64 (lub ≤ 68/70) wierzchołkach zawiera C8, C16 lub C32” oraz rozkład najmniejszej długości cyklu potęgi dwójki.
- **Dlaczego otwarte:** katalogi (18 + 474 + 27 169 + 1 408 813 grafów dla n = 58…64) istnieją,\[33\] ale nie znalazłem publikacji badającej w nich cykle C16/C32.\[33\] Zakres n > 48 jest poza D–D.
- **Plan:** pobrać graph6 z House of Graphs i puścić bitsetowy test C16/C32 (≈ 1,44 mln grafów, minuty). Dla n = 66–70 napisać generator talii ≥ 9 z **przycinaniem C16 w trakcie budowy** (kanoniczna augmentacja à la McKay; częściowy graf z C16 jest odrzucany). Szacunkowe liczności bez przycinania, przy wzroście ok. 50× na krok: ~7·10⁷ (66), ~3·10⁹ (68), ~10¹¹ (70), co jest ekstrapolacją, a nie daną. Z przycinaniem C16 przestrzeń zmaleje radykalnie.
- **Wartość:** samodzielnie skromna, ale w połączeniu z P1 i P3 daje spójny artykuł „wysoka talia”. Dodatkowo dostarcza grafy talii ≥ 9 z rzadkimi C16 jako seedy do P1.
- **Ryzyko:** niskie. **Walidacja:** odtworzenie liczności 18/474/27 169/1 408 813 przez własny generator.

### P3. Kubiczne dwudzielne n = 70 (i 72): domknięcie przez klatki + rozszerzenie Zhuge

- **Cel:** wykazać, że każdy kubiczny dwudzielny graf na 70 (72) wierzchołkach ma C4, C8 lub C16 (lub C32), co daje dolne ograniczenie ≥ 72 (74).
- **Kluczowa obserwacja (nowa):** w kubicznym dwudzielnym grafie bez C4 i C8 albo jest C6 (wtedy działa metoda Tranquilliego/Zhuge z trójkątem Berge'a), albo talia ≥ 10, a dla n = 70 oznacza to **jedną z 3 (3,10)-klatek** (Balaban 10-cage, graf Harriesa, graf Harriesa–Wonga; wszystkie dwudzielne). Talia 12 wymaga 126 wierzchołków. Przypadek talii ≥ 10 sprowadza się więc do sprawdzenia trzech grafów, a przypadek C6 do uruchomienia kodu Tranquilliego/Zhuge z limitem 35 punktów.
- **Koszt:** limit 29 dał 1 762 368 prób (Tranquilli);\[13\] limity 34→35 to prawdopodobnie kilka razy więcej niż Zhuge, czyli dni CPU. Dla n = 72 potrzebna jest dodatkowo lista kubicznych grafów talii ≥ 10 na 72 wierzchołkach (mała, do wygenerowania).
- **Wartość:** czysty, krótki wynik. Ryzyko: niskie; jedyna pułapka to poprawność rozszerzenia kodu. **Walidacja:** odtworzenie strumieni Tranquilliego dla limitu 29 (zgodność haszy transkryptów).

### P4. Niezależna, certyfikowana weryfikacja D–D (n ≤ 40) inną metodą i rozszerzenie do n = 41–42

- **Dlaczego:** D–D nie wygenerowali dowodów, a test minimalności SMS ma limit kroków („a class may therefore be reported more than once, but no class is lost”).\[2\] Niezależne potwierdzenie z certyfikatami ma realną wartość publikacyjną.
- **Plan:** generator przez kanoniczną augmentację (nie SMS) z ograniczeniami (R1), (R2), (C2), (C3). Dodatkowo **dwuspójność dla parzystych n** (Wn. 2.4) i struktura z Tw. 2.3 dla nieparzystych n. W CNF dwuspójność kosztowała +41–62%, ale w generatorze to tani test liniowy na liściach i prefiksach, czyli przewaga metodologiczna. Równoległość przez podział drzewa (smart cubing lub prefiksy).
- **Koszt:** D–D n = 40 to 220 309 s na rdzeń (E2).\[2\] n = 41–42 to szacunkowo 2–4× więcej na każde n, czyli tygodnie na 64 rdzeniach. **Ryzyko:** średnie (wydajność własnego generatora).

### P5. Tryb „jednego bloku” (Hip. 4.1) jako częściowy dowód hipotezy D–D o dwuspójności

- **Obserwacja:** z Tw. 2.3 nie-dwuspójny minimalny kontrprzykład rzędu 2m + 1 rozkłada się na dwa bloki rzędu m + 1. Każdy blok jest **2-zdegenerowany**, ma dokładnie jeden wierzchołek stopnia 2, pozostałe stopnia ≥ 3, i nie ma cykli 2^k.\[2\] Wyczerpanie takich grafów do rzędu M dowodzi, że **każdy minimalny kontrprzykład rzędu ≤ 2M − 1 jest dwuspójny**.
- **Plan:** generator z warunkiem 2-zdegenerowania (bardzo silne przycinanie: m_edges ≤ 2(m+1) − 3) i jednym wierzchołkiem stopnia 2.
- **Wartość:** konkretny postęp w kierunku hipotezy z §6 D–D, przy umiarkowanym koszcie. **Ryzyko:** niskie–średnie.

### P6. Przegląd censusów symetrycznych (VT ≤ 1280, symetryczne ≤ 2048)

- **Cel:** „każdy kubiczny graf wierzchołkowo-przechodni na ≤ 1280 wierzchołkach zawiera C4, C8, C16 lub C32” wraz z listą wyjątków wymagających C64+.
- **Dlaczego:** Burkhart nie obejmuje grafów kubicznych (parzysty rząd), a Gebendorfer obejmuje tylko dwudzielne grafy talii 6.\[16\]\[21\]\[22\]\[40\] Pełnego przeglądu nie znalazłem.
- **Koszt:** 111 360 grafów,\[41\] test C16/C32 przez MitM, czyli godziny–dni.\[42\] Wartość: umiarkowana, ale bardzo tania. Grafy z najmniejszym cyklem potęgi dwójki ≥ 32 to idealne seedy dla P1 i silnika.

### P7 (opcjonalny). Automatyczne odkrywanie konfiguracji redukowalnych

Wzorzec z CP 2025 (3-dekompozycja, Zhang–Szeider): SMS + GSS uczący się zakazanych częściowych podgrafów w minimalnym kontrprzykładzie. Dla EGC kandydaci to podgrafy, które po zastąpieniu mniejszym gadżetem o tym samym „spektrum okien” (rachunek okien Garcii) dają mniejszy kontrprzykład. Wysokie ryzyko, ale potencjalnie nowa teoria.

**Nie rekomenduję:** grafów planarnych przez plantri (n ≤ 40 jest już pokryte ogólnie, a większe n jest nieosiągalne) ani wyliczania talii ≥ 5/6/7 snarkhunterem powyżej 48 (2,2·10¹¹ grafów już przy talii ≥ 7, n = 40).\[33\]

## 5. Uzupełnienia do punktów (3)–(6) oryginalnego promptu

**(3) Kodowania deklaratywne:**
- Liczby D–D, których brakowało w poprzednim raporcie: częstotliwość propagatora 30 → 5 daje ok. 10× (n = 29). E2 vs E0 to 2,6–4,9×. Dwuspójność w CNF (drzewo rozpinające z rangami dla każdego grafu bez wierzchołka) to +41–62%.\[2\]
- Garcia (CEGAR): blokowanie do 400 cykli C8 na model. Koszt rośnie „roughly 3–4 per vertex”; autor sam wskazuje redukcje minimalnego kontrprzykładu jako dźwignię.\[3\]
- Nowe narzędzia: smart cubing (CP 2026), co-certificate learning (Kirchweger–Peitl–Szeider, „Co-Certificate Learning with SAT Modulo Symmetries”, IJCAI 2023, arXiv:2306.10427), Q-static symmetry breaking (AAAI 2025).
- Tw. 4.4 D–D daje **alternatywne kodowanie dla przypadku dwudzielnego**: szukanie tęczowych cykli w grafie kolorowanym krawędziowo, w którym każdy kolor to klika ≥ 3.\[2\] To jest analog konfiguracji Tranquilliego dla dowolnego stopnia ≥ 3.

**(4) Seedy:**
- (3,9)-klatki (18 grafów, 58 wierzchołków) i grafy talii 9 dla n = 60–64: automatycznie bez C4 i C8.
- (3,10)-klatki (3 grafy, 70 wierzchołków, dwudzielne).\[43\]
- Graf 370-wierzchołkowy Henry'ego (bez C4…C32) jako materiał do ekscyzji.\[23\]
- Gadżety Garcii: S_{H7}(u,v) = S_{H7}(u,w) = {2,…,6}, S_{H7}(v,w) = {3,…,6}, 𝒞(H7) = {3,5,6,7}. 78 jest optymalne tylko dla baz ≤ 12, więc warto szukać baz 14–20.\[3\]
- Kubiczne VT grafy dwudzielne talii 6 (Gebendorfer) są bezużyteczne jako seedy, bo zawsze mają cykl 2^k.\[22\]

**(5) Funkcje celu i operatory:**
- Nowy surogat z Tranquilliego: **graf zgodności wierzchołków deficytowych**. Para (x, y) jest „zgodna”, jeśli nie ma między nimi ścieżki prostej długości 2^k − 1 dla k = 2, 3, 4. Wtedy dodanie krawędzi nie tworzy C4/C8/C16. W wariancie konfiguracyjnym dodanie bloku wymaga trójkąta w grafie zgodności.\[13\] Liczba i struktura zgodnych par to miara „dokańczalności” częściowego grafu, użyteczna jako lookahead w konstruktywnym budowaniu zamiast mutacji pełnego grafu.
- Operator „zamiany brzegu” cięcia 3-krawędziowego z identycznością funkcji tworzącej cykli (gsidoine, N, do weryfikacji).\[26\]

**(6) Detekcja:**
- Tranquilli potwierdził na poziomie haszy transkryptów zgodność DFS i łączenia 7-krawędziowych półścieżek (MitM 7+7) dla C16.\[13\]
- Lemat 7: nowy C16 po dodaniu wierzchołka b z sąsiadami B istnieje wtedy i tylko wtedy, gdy w starym grafie jest ścieżka prosta długości 14 między dwoma elementami B.\[13\] Analogicznie dla dodania krawędzi uv: C_L powstaje wtedy i tylko wtedy, gdy istnieje ścieżka prosta u–v długości L − 1. To jest **przyrostowa** wersja testu, idealna do delta-oceny ruchów.

## 6. Ocena zmian dla silnika Rust

Stan repozytorium (tylko README; dokumentacji w `docs/reports` nie przejrzałem, bo pobieranie było ograniczane): `sglab` to system kampanii z AI Research Director, lane'ami z checkpointami, niezależnymi weryfikatorami Python i C++ oraz granicą certyfikacji M4.\[44\] Repozytorium ma 196 commitów i 13 otwartych issues; widoczne są katalogi `rust/sglab-engine`, `tools/extremal` i `artifacts/proposal-ranking/mutation_forge_stage4r_v1`.\[44\] Na profilu są też `heg-gpu-lab` (CUDA) i `mutation-forge-lab` (LLM-ewolucja polityk mutacji).\[37\] **Luka:** README nie pokazuje dokładnego lane'a enumeracyjnego z certyfikatami ani trybu problemów ekstremalnych f(k). Co ważniejsze, heurystyczne szukanie kontrprzykładu dla n ≤ 40 (ogólne), n ≤ 48 (kubiczne) i n ≤ 66 (dwudzielne) jest już bezcelowe w świetle D–D.

| # | Zmiana | Nowość względem 7 poprzednich rekomendacji | Potencjał | Koszt / złożoność |
|---|---|---|---|---|
| 1 | **Tryb f(k) / prefiks {4, 8, 16}** (cubic-only, n = 54…76), seedy z klatek talii 9 | **Nowe** | Bardzo wysoki (P1) | Niski: zmiana funkcji celu i źródła seedów |
| 2 | **Przyrostowa wyrocznia C_L dla dodania krawędzi**: test ścieżki prostej długości L − 1 przez bitsetowe MitM (7+7 dla C16, 15+16 dla C32) | Nowe jako wersja przyrostowa (poprzednio MitM tylko jako weryfikator) | Wysoki: przyspiesza delta-ocenę 3-switchów | Średni |
| 3 | **Lane dokładny: kanoniczna augmentacja + strumienie certyfikatów** (świadek cyklu dla każdej odciętej gałęzi; tani checker), z dwuspójnością jako filtrem prefiksów | **Nowe** | Wysoki (P3, P4, P5, publikowalność) | Wysoki |
| 4 | **Smart cubing / podział prefiksów** dla zewnętrznego SMS (n = 41–42, f(4) dolne) | **Nowe** | Średni–wysoki | Niski–średni (skrypty wokół SMS) |
| 5 | **Lookahead „grafu zgodności”** w konstruktywnej fazie (budowa grafu od klatki/rdzenia z dokańczaniem) | **Nowe** | Średni: nowy sposób na płaskowyż C16 | Średni |
| 6 | **Tryb jednego bloku z 2-zdegenerowaniem** (Hip. 4.1, P5) | Rozszerzenie poprzedniej rek. 1 o warunek 2-zdegenerowania i interpretację „dwuspójność do 2M − 1” | Średni | Niski |
| 7 | **Filtr Tw. 3.8 D–D** (brak 2^j-podziałów multigrafów o δ ≥ 3; dla j = 1 multigraf M z Lematu 3.5 musi być prosty, bez cykli 2^k i 2-zdegenerowany) | Rozszerzenie filtra D–D | Niski–średni (głównie dla grafów niekubicznych) | Niski |

**Plan walidacji:**
- (1) odtworzyć f(3) = 24 i spektrum grafów Markströma;
- (2) porównać wyrocznię przyrostową z pełnym DFS na 10⁶ losowych ruchów (zero rozbieżności);
- (3) odtworzyć liczności `genreg` dla talii ≥ 9 (58–64) oraz liczby konfiguracji v₃ z tabeli Tranquilliego (v = 7…13: 1, 1, 3, 10, 31, 229, 2036);\[13\]
- (4) przed publikacją puścić każdy wynik ujemny przez dwa niezależne weryfikatory, co Twój M4 już wspiera.

## Zastrzeżenia

- Większość prac z 2026 r. to **preprinty lub Zenodo**, często jawnie wspomagane przez LLM (Tranquilli, Garcia, Culus, Henry, mcolsen). Żadna z kluczowych granic obliczeniowych z 2026 r. nie jest jeszcze recenzowana. Wyniki D–D nie mają certyfikatów.
- Szacunki kosztów P1, P2 i P4 to **ekstrapolacje** z czasów D–D i liczności z House of Graphs, a nie pomiary.
- Nie zweryfikowałem: rekordu Zenodo 22019344, przyjęcia Carra do BICA, ID arXiv dla Liu–Montgomery i Hu–Shen, adresu repozytorium kodu D–D, wariantu „talia 12” Gebendorfera, grafu talii 16 na 702 wierzchołkach (Henry), wyniku Markströma f(4) ≥ 54 (nieopublikowany) ani szczegółowych logów i raportów w `hipotures/heg/docs`.
- Liczności grafów talii ≥ 9 dla n = 60–64 pochodzą z jednego obliczenia (McKay i in.), niezależnie potwierdzonego tylko dla n = 58.\[33\] Twój P2 dałby przy okazji drugie potwierdzenie.

## Sources

1. [\[2609.28594\] Towards a more structured search for Erdős-Gyárfás counter-examples](https://arxiv.org/abs/2609.28594)
2. <https://arxiv.org/pdf/2609.28594>
3. [Small graphs without power-of-two cycles:a lower bound of 24, a correction to a construction of Exoo,and explicit bounds for 𝑓(𝑘)](https://arxiv.org/html/2609.04686)
4. [Preregister: prove Ducoffe–Dumitru's conjecture that minimal bipartite Erdős–Gyárfás counterexamples are 2-edge-connected (arXiv:2609.28594 §6, Erdős #64) · Issue #14778 · the-omega-institute/trureturing · GitHub](https://github.com/the-omega-institute/trureturing/issues/14778)
5. [Every Minimal Counterexample to the Erd\\H{o}s-Gy\\'arf\\'as Conjecture is Predominantly Cubic](https://arxiv.org/abs/2605.22844)
6. [Every Minimal Counterexample to the Erd\\H{o}s-Gy\\'arf\\'as Conjecture is Predominantly Cubic](https://arxiv.org/pdf/2605.22844)
7. [Erdős-Gyárfás Conjecture -- from Wolfram MathWorld](https://mathworld.wolfram.com/Erdos-GyarfasConjecture.html)
8. [Cycles of Length 4 or 8 in Graphs with Diameter 2 and Minimum Degree at Least 3](https://arxiv.org/html/2508.19302)
9. [Small graphs without power-of-two cycles: a lower bound of 24, a correction to a construction of Exoo, and explicit bounds for f(k)](https://arxiv.org/abs/2609.04686)
10. [GitHub - ArjunBalaji79/erdos-gyarfas-min-degree-3: SAT verification of the Erdos-Gyarfas conjecture for minimum-degree-3 graphs: every such graph on \<=30 vertices contains a power-of-two cycle (counterexample bound \>=31) · GitHub](https://github.com/ArjunBalaji79/erdos-gyarfas-min-degree-3)
11. [A 60-Vertex Lower Bound for Cubic Bipartite Counterexamples to the Erdős–Gyárfás Conjecture](https://arxiv.org/html/2608.02675)
12. [\[2608.02675\] A 60-Vertex Lower Bound for Cubic Bipartite Counterexamples to the Erdős-Gyárfás Conjecture](https://arxiv.org/abs/2608.02675)
13. <https://arxiv.org/pdf/2608.02675>
14. [Reproducibility Artifact for a 70-Vertex Lower Bound for Cubic Bipartite Counterexamples to the Erdős–Gyárfás Conjecture](https://zenodo.org/records/21981786)
15. [Power-of-two cycles in projective cubic graphs of large edge-width](https://arxiv.org/pdf/2610.26403)
16. [\[2611.05060\] Odd-ordered Cayley graphs satisfy Erdős--Gyárfás](https://arxiv.org/abs/2611.05060)
17. [Odd-ordered Cayley graphs satisfy Erdős–Gyárfás](https://arxiv.org/html/2611.05060)
18. [arXiv:2410.22842v2 \[math.CO\] 11 Feb 2025 Erdős-Gyárfás conjecture on graphs](https://arxiv.org/pdf/2410.22842)
19. [Three Graphs and the Erdős-Gyárfás Conjecture](https://arxiv.org/abs/1403.5636)
20. [New Small Regular Graphs of Given Girth: the Cage Problem and Beyond](https://www.combinatorics.org/ojs/index.php/eljc/article/view/v33i3p48)
21. [Erdős64: cubic bipartite vertex-transitive girth-six variant and a hexagon-factor theorem · Issue #7281 · google-deepmind/formal-conjectures · GitHub](https://github.com/google-deepmind/formal-conjectures/issues/7281)
22. [Jonas GEBENDORFER](https://www.researchgate.net/profile/Jonas-Gebendorfer)
23. [Improved cubic graph constructions avoiding power-of-two cycle lengths](https://zenodo.org/records/23886386)
24. [GitHub - mcolsen/erdos-gyarfas · GitHub](https://github.com/mcolsen/erdos-gyarfas)
25. [CUBIC VERTEX-TRANSITIVE GRAPHS OF GIRTH SEVEN MARUˇSA LEKˇSE AND MICAEL TOLEDO](https://arxiv.org/pdf/2508.19880)
26. [Erdős–Gyárfás #64: exact 3-cut cycle-spectrum rewrite calculus by gsidoine · Pull Request #13 · gsidoine/rewriting-graph-conjectures · GitHub](https://github.com/gsidoine/rewriting-graph-conjectures/pull/13)
27. [GitHub - FragileTech/hypostructure · GitHub](https://github.com/FragileTech/hypostructure)
28. [GitHub - adamben04/solved-conjectures: math drop, curated by myself and 6.2-astra · GitHub](https://github.com/adamben04/solved-conjectures)
29. [GitHub - Drill23/erdos-64-lean4 · GitHub](https://github.com/Drill23/erdos-64-lean4)
30. [Lemnis — Erdős #64: power-of-two cycle exclusion · Issue #47 · d3lefts/d3lefts · GitHub](https://github.com/d3lefts/d3lefts/issues/47)
31. [On monochromatic path covers conjecture of Erdős–Gyárfás](https://arxiv.org/pdf/2607.21915)
32. [Hai Xia - Algorithms and Complexity Group - TU Wien](https://www.ac.tuwien.ac.at/people/hxia/)
33. [Connected cubic graphs](https://houseofgraphs.org/Cubic)
34. [Automorphism group certificates for cubic vertex-transitive graphs](https://zenodo.org/records/19560683)
35. [PatternBoost: Constructions in Mathematics with a Little Help from AI Fran¸cois](https://arxiv.org/pdf/2411.00566)
36. [\[2511.02864\] Mathematical exploration and discovery at scale](https://arxiv.org/abs/2511.02864)
37. [GitHub - hipotures/hipotures: GitHub profile README · GitHub](https://github.com/hipotures/hipotures)
38. <https://arxiv.org/pdf/2511.07247v2>
39. [GitHub - AGT-Kulak/smallRegGirthGraphs: Code and data related to the manuscript "G. Exoo, J. Goedgebeur, J. Jooken, L. Stubbe and T. Van den Eede. New small regular graphs of given girth: the cage problem and beyond, manuscript". · GitHub](https://github.com/AGT-Kulak/smallRegGirthGraphs/tree/main)
40. [Odd-ordered Cayley graphs satisfy Erd\\H{o}s--Gy\\'arf\\'as](https://arxiv.org/pdf/2611.05060)
41. [Cubic Vertex-Transitive Graph -- from Wolfram MathWorld](https://mathworld.wolfram.com/CubicVertex-TransitiveGraph.html)
42. [A survey of repositories in graph theory](https://arxiv.org/pdf/2006.12741)
43. [Cages](https://aeb.win.tue.nl/graphs/cages/cages.html)
44. [GitHub - hipotures/heg: Structural Graph Conjecture Lab: reproducible AI-directed searches for counterexamples to the Erdős–Gyárfás conjecture. · GitHub](https://github.com/hipotures/heg)
