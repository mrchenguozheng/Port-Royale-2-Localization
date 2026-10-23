# Glossary

Proper nouns in the game (goods, ships, ranks, towns, …) are spread over more than
3,000 strings. The same English term can otherwise end up translated differently
in different letters. This folder extracts them by group with **English, Chinese
and French side by side**, for reference and review.

[中文说明](README.zh-CN.md)

## Sources only

| File | Purpose |
|---|---|
| `terms.toml` | Term list: which strings are terms and which group they belong to. The only hand-maintained file |
| `README.md` | This file |

Generated tables are **not** committed (`build/` is gitignored):

| Output | Description |
|---|---|
| `build\glossary\zh.md` | Chinese table with a French reference column |
| `build\glossary\zh.csv` | Same data as CSV (UTF-8 BOM, opens cleanly in Excel) |
| `build\glossary\<lang>.md` | Appears automatically for other languages |

The table is computed from `terms.toml` + translations, so it goes stale as soon as
translations change. Committing it would only add a copy that is guaranteed to age.

## Regenerate

```bat
python src\tools\glossary.py                 :: Chinese table (with French column)
python src\tools\glossary.py --csv           :: also export CSV
python src\tools\glossary.py --with fr.gog_1.1.2.42   :: reference language
python src\tools\glossary.py --out D:\out    :: output directory
```

The build also regenerates it, so the normal workflow does not need a separate run.

Translations are read from `src\translations\` at generation time; they are not
duplicated into the term file.

## Polysemy: May / Jan

Some English words are months, names or verbs:

- `Jan`: one entry is January, another is the name "Jan";
- `May`: one is the month, another is "May" in a date abbreviation;
- `Load`: one is "load a save", others are "load cargo".

Terms are therefore **matched by id**, not by English text. Each generated group
also lists other entries with the same English text but different translations.

## Writing terms.toml

One `[[group]]` per group:

```toml
[[group]]
name = "Goods"
note = "Commodities traded at the market"   # optional; shown as the group note
range = ["0x37328fb9", "0x37329033"]        # id range
max_len = 24                                # optional: skip long sentences in the range

[[group]]
name = "Nations"
ids = ["0xf90d7ea2", "0xf90d7ea3", "0xf90d7ea5"]   # exact ids for scattered entries
```

Entries of the same kind are usually contiguous in the string table, so `range`
is easier to maintain; use `ids` for scattered entries.

To find an id, select the entry in the editor; it shows the id.

## Adding a language

1. Add `src\translations\<lang>.toml` (the editor's "＋ Add language" does this);
2. Run `python src\tools\glossary.py --lang <lang>`;
3. Do not edit `terms.toml`: terms are id-based and language-independent;
4. To display a language name, add it to `LANG_NAMES` in `src\tools\glossary.py`.

Reference originals can be exported too:

```bat
python src\tools\glossary.py --lang fr.gog_1.1.2.42
```

## Known inconsistencies

- "May": `0x327c63bf` is the month, `0x0247d1b7` is the date abbreviation "May";
- Other months also have two forms: month name vs date abbreviation;
- `Jan` as a person name is "Jan", not the month.

## Automatic terminology check

`terms_check.py` uses the glossary as rules:

```bat
python src\tools\terms_check.py            :: all editable languages
python src\tools\terms_check.py --lang zh
python src\tools\terms_check.py --json     :: for editors/scripts
python src\tools\terms_check.py --strict   :: exit 1 on findings (CI)
```

Rule: if the source contains `Frigate`, the translation should contain the agreed
term. Matching is whole-word, case-sensitive for capitalized forms, plural only
with `s`, longer terms first, spaces ignored in translations, and a translation
containing the agreed term passes.

Overrides in `terms.toml`:

```toml
[[group]]
name = "UI"
check = false

[group.alt]
"0xdc939a60" = ["Church"]    # Catholic Church

ignore = ["0xfc512ea5"]       # RAD Game Tools in a copyright notice
```

The editor also runs the check and shows the count of pending terminology fixes.
