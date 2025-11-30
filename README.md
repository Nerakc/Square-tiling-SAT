# Square Tiling - SAT solver

Tento projekt převádí úlohu pokrytí čtvercové mřížky dlaždicemi (square tiling) na SAT v CNF formátu a řeší jej externím voláním SAT solveru `glucose-syrup` pro ověření splnitelnosti a získání modelu (v tomto případě předkompilovaného [Glucose 4.2](https://github.com/audemard/glucose/)).

**Stručný obsah**
- **Problém**: pokrytí `k x k` čtvercové mřížky dlaždicemi, přičemž každá dlaždice má barvy na čtyřech stranách (nahoře, vpravo, dole, vlevo). Sousedi musí mít shodné barvy na společných hranách.
- **Skript**: `square_tiling.py`
- **Instanční soubory**: ve složce `instances/` jsou tři připravené instance: malá splnitelná (`solvable.txt`), malá nesplnitelná (`unsolvable.txt`) a větší/ne-triviální (`non-trivial.txt`).

**Přesný popis problému**
- Vstupní parametr `k` určuje rozměr mřížky `k x k`.
- Dlaždice (tile) jsou typy popsané čtyřmi barvami: pořadí stran v souboru je `(nahoře, vpravo, dole, vlevo)`.
- Cílem je přiřadit každé pozici `(i,j)` v mřížce právě jeden typ dlaždice tak, aby pro každou sousední dvojici buněk barvy na sdílené hraně byly stejné.
- Rozhodovací proměnné: pro každou pozici `(i,j)` a každý typ dlaždice `t` je booleovská proměnná (pravda = na pozici použito `t`).

**Zakódování do CNF (popis použitý v `square_tiling.py`)**
- Proměnné jsou pojmenovány jako `ii jj tt` — konkatenace indexů `i`, `j` a `t` (vše 1-based a zero-padded tak, aby šířky byly konzistentní). Např. pro `k=8` a 12 typů může jméno vypadat jako `1203` (příklad formátu závisí na šířkách i,j,t v desítkovém zápisu).
- Klauzule:
  - Pro každou pozici `(i,j)` je klauzule „alespoň jedna dlaždice“: (x_{i,j,1} ∨ x_{i,j,2} ∨ ...)
  - Pro každou pozici a každé dvojici typů `(t1,t2)` s `t1 != t2` klauzule „ne více než jedna“: (¬x_{i,j,t1} ∨ ¬x_{i,j,t2}) — tedy zajištění exaktně jednoho typu na pozici.
  - Pro každou sousední dvojici buněk (vpravo nebo dolů) a pro každý pár typů, které na společné hraně nemají stejnou barvu, přidat klauzuli zakazující jejich současné použití: (¬x_{i,j,t1} ∨ ¬x_{i',j',t2}).
- Poznámka: generovaný výstup v `output.cnf` obsahuje hlavičku `p cnf NUMV NUMC` a pak klauzule, nicméně proměnné se v souboru zapisují pojmenovaně (textové tokeny vzniklé z indexů), tedy né všechna čísla od 1 do NUMV nutně musí být použita. a NUMV je v toto případě indentifikátor nejvyšší použité proměnné, nikoli realný počet proměnných, jelikož `glucose-syrup` očekává číselné proměnné v rozsahu `1..NUMV`.

**Formát vstupu** (`instances/*.txt`)
- První řádek může obsahovat číslo (volitelně) — pokud je pouze jedno číslo na prvním řádku, ignoruje se (slouží pro případné poznámky), mělo by obvykle udávat počet barev, které jsou použity v následujících definicích dlaždic, avšak se reálně nevyužívá (pozůstatek po původní verzi).
- Následuje řádek se seznamem barev oddělených mezerou, např. `red green blue yellow`.
- Každý další řádek popisuje typ dlaždice čtyřmi barvami (nahoře, vpravo, dole, vlevo). Barvy lze zapsat jako `<red,blue,red,green>` nebo prostě `red blue red green`.
- Typů dlaždic může být libovolný až libovolně velký počet (v rámci paměťových limitů), avšak musí být alespoň dvě (`glucose-syrup` má problém s instancemi s jediným typem, u kterého se mi nepodařilo najít příčinu).

**Použití skriptu**
- Spuštění (předpoklad Linux nebo WSL):
```
python3 ./square_tiling.py <k> ./instances/<soubor.txt>
```
- Pro výpis DIMACS do konzole:
```
python3 ./square_tiling.py <k> ./instances/<soubor.txt> --print-dimacs
```
- Pro výpis statistik solveru:

```
python3 ./square_tiling.py <k> ./instances/<soubor.txt> --solver-stats
```

- Po vygenerování `output.cnf` skript volá `./glucose-syrup -model output.cnf` (spouštěč v kořeni projektu). Ujistěte se, že `glucose-syrup` je spustitelný (v WSL použijte `chmod +x glucose-syrup` pokud je potřeba).

**Výstup**
- Pokud je problém nesplnitelný: skript vytiskne `s UNSATISFIABLE` a vrátí návratový kód `20`.
- Pokud je splnitelný: skript vytiskne `s SATISFIABLE`, následně `Model:` a maticový zápis vybraných typů dlaždic (číselné indexy typů od 1) pro každou řádku mřížky.

**Přiložené instance (soubor `instances/`)**
- `solvable.txt` — malá, člověkem analyzovatelná splnitelná instance:
  - `k=4`
  - barvy: `red green blue yellow`
  - 2 typy dlaždic, které lze střídavě použít; instance je splnitelná.
- `unsolvable.txt` — malá, člověkem analyzovatelná nesplnitelná instance:
  - `k=4`
  - stejné barvy, ale druhý typ dlaždice má incompatibility vedoucí k neřešení — výsledkem je UNSAT.
- `non-trivial.txt` — větší/ne-triviální instance připravená pro experimenty:
  - `k=50`
  - osm barev a více typů dlaždic (více symetrií a kombinací). Tento soubor slouží jako „ne-triviální“ testovací instance.
  - Pro dosažení doby běhu ≥10s na některých strojích je třeba navýšit `k` pro ztížení problému. 

**Prováděné experimenty a výsledky**
- Prosté spuštění v PowerShellu vedlo k chybě (WinError 193) protože `glucose-syrup` v kořeni je Linuxový binární — proto testujte v WSL nebo v Linuxu.
- V WSL jsem spustil:
```
wsl bash -lc "time python3 ./square_tiling.py 8 ./instances/non-trivial.txt --solver-stats"
```
  - Výsledek: instance byla vyřešena jako SAT velmi rychle (reálný čas ~0.42 s na mém stroji, solver reportoval CPU time ≈ 0.285 s). Takže tato instance NESPLOŇUJE požadavek „běží alespoň 10s". Pro dosažení požadovaného výsledku jsem musel navýšit `k` alespoň na 50, kdy doba běhu vzrostla na ~14s.
  - Pro vstupy s jednou dlaždicí hlásil `glucose-syrup` chybu `floating point exception (core dumped)` — proto je třeba mít alespoň dva typy dlaždic. Problém se mi nepodařilo dále analyzovat.