# Legal Reviews Dashboard (CZ)

Statický dashboard nad recenzemi advokátních kanceláří.

## Jak aktualizovat data (nejjednodušší workflow)
1. Nahraj / přepiš soubory v `data/` (např. `data/source_a.json`, `data/source_b.json`, …).
2. Push do GitHub repozitáře.
3. GitHub Action automaticky:
   - validuje JSONy (pokud některý nejde načíst, přeskočí ho a zapíše limitation),
   - sloučí firmy/pobočky,
   - deduplikuje recenze,
   - vygeneruje `public/meta.json` (dashboard čte jen tento soubor).

Dashboard pak jen deployneš na Vercel (statický web).

## Lokální build
```bash
python3 scripts/build_meta.py
```

## Poznámky
- Pokud některý vstupní JSON není validní, build ho přeskočí (bez domýšlení dat).
- Ranking v UI má filtr `Min n` – čím nižší n, tím méně stabilní pořadí.
