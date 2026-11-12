# Language rule interface (three parts)

Every language in `lang_rules` does exactly one thing: declare a `LangSpec`.
Punctuation, segmentation and spacing are three independent concerns; folding them into
one `normalize()` forced a new language to touch `engine_text`, `apply_*_rules` and
`normalize_text` at the same time.

Code: `src/tools/text/lang_rules/spec.py`.

---

## 1. The three parts

### Punctuation

```python
class Punctuation:
    normalize(text, date_format=False) -> str
    tables            # for inspection: open/close/single/runs/cjk
```

A pure function that only touches punctuation: half-width → full-width, one space after
single marks, spaces outside paired marks, spaces around placeholders, no spaces around
`<n>`. It never tokenizes and never adds layout spaces, so `normalize_text.py` can safely
write its output back into the translation layer.

The machinery still lives in `base.py`: `make_fmt` / `fix_ascii_punct` / `fix_vars` / `clean_n`.

The placeholder regex has exactly one language-wide source, `base.VAR`: Chinese's
`zh_space.TAG` and `zh_pipeline.SPLIT_RX` are assembled from it (each adds a `<...>`
alternative). Japanese's `ja.SPLIT_RX` is deliberately wider (`%[0-9A-Za-z]+`,
`@X$…$`) and stays separate. The validation contract in `shared/core/validate.py` is
independent and is not derived from `base.VAR`.

### Segmenter

```python
class Segmenter:
    name                       # "spacy" / "jieba" / "janome" / "none"
    prepare(texts) -> ctx      # batch preparation; None when unnecessary
    tag(text) -> [(surface, pos)]   # None when POS is unsupported
```

`prepare` must be batched: Chinese hands all runs to one subprocess, Japanese reuses one
tagger. Per-entry preparation would turn a build from seconds into many minutes and rebuild
the model every time. `tag` is only used by languages that need POS (Japanese particles);
Chinese only takes `surface`.

No tokenizer? Declare `NullSegmenter()` with `name="none"`; the spacing strategy decides the
fallback.

### Spacing

```python
class Spacing:
    mode                       # "none" / "group" / "particle"
    setup(doc)                 # once per document (Chinese name tables)
    pre_punct(text) -> str     # before punctuation normalization (Japanese particles)
    before(text) -> (str, meta)  # after punctuation, before segmentation (Chinese conj/names/tokens)
    prepare(texts, segmenter) -> ctx
    apply(text, ctx) -> str
    report()                   # end-of-run notice
```

| mode | For | Behaviour |
|---|---|---|
| `none` | languages whose words are already space-separated (en, fr, de, ko, …) | pass through, the old `else` branch |
| `group` | Chinese-style (no spaces between words) | group words by a character budget, one space between groups, `max_chars` = 10 |
| `particle` | Japanese-style | morphological analysis, one space after particles |

`particle` uses `pre_punct`: it must run **before** punctuation. Punctuation adds its own
spaces, and reversing the order makes the two interfere. `group` uses `before` + `prepare` +
`apply`, i.e. the two-pass flow: first pass up to "pre-tokenization", second pass batched
tokenization plus grouping.

---

## 2. Execution order

```python
out, stats, seg_name = spec.build_texts(spec, doc, order)
```

1. `spacing.setup(doc)` — once per document;
2. per entry: `spacing.pre_punct()` → `punct.normalize()` → `spacing.before()`;
3. `spacing.prepare(all intermediate texts, segmenter)` — batched tokenization;
4. per entry `spacing.apply()`;
5. `spacing.report()`.

`engine_text.build(lang, doc, order)` is just `build_texts(get_spec(lang), …)`; no
`if lang == …` dispatch remains inside it.

---

## 3. Where Chinese and Japanese land

| Part | Chinese | Japanese |
|---|---|---|
| Punctuation | `lang_rules/zh.normalize` | `lang_rules/ja.normalize_punct` |
| Segmenter | `ZhSegmenter` (`zh_space.segment`: spaCy → jieba) | `JaSegmenter` (`_Tagger`: janome → fugashi) |
| Spacing | `ZhGroupSpacing` (`zh_pipeline.pre_space` + `zh_space.spaced`) | `JaParticleSpacing` (`space_particles_analyzer`) |

The Chinese conjunction, name and digit/dash/`<n><n>` steps live in `zh_pipeline.py`: they
decide by "is the neighbour a Han character", which only Chinese needs, so they do not go
into `base.py`.

---

## 4. Adding a language

Korean (words already space-separated) needs one file, `lang_rules/ko.py`:

```python
LANG = "ko"
PUNCT = {...}
ASCII = {...}
FMT, PUNCT_CHARS = base.make_fmt(PUNCT)
CJK_RX = re.compile(...)

def normalize(text, date_format=False):
    ...

def spec():
    return S.LangSpec(code=LANG,
                      punct=S.Punctuation(normalize, {"lang": LANG, **PUNCT}),
                      segmenter=S.NullSegmenter(),
                      spacing=S.NoSpacing())
```

Then add `"ko"` to `REGISTRY` in `lang_rules/__init__.py`. `engine_text.py`,
`apply_*_rules.py` and `normalize_text.py` do not change at all.

For a language that does not separate words with spaces, replace `spacing` with your own
`Spacing` implementation and set `mode` to `group` (character budget) or a new mode of
your own; the interface does not prescribe grouping internals.

---

## 5. Acceptance (an interface change must not change behaviour)

- `python src\tools\text\engine_text.py --lang zh --check` and `--lang ja --check` must
  print "一致。";
- both packs recompile to the same SHA-256 as before the refactor
  (`build/PR2Packs/zh.txt`, `ja.txt`, 3548 entries each);
- `python tests\test_rules.py`, `tests\test_validate.py`, `tests\test_server_api.py` and
  `python src\tools\check.py` all pass.

`engine_text.py` is the only build entry point (`--lang zh|ja`, `--check` to compare,
`--stats` for per-stage counts, `--diff` to print each difference). The old Chinese names
remain importable from `apply_zh_rules` (`fix_conj`, `space_tokens`, `build_names`,
`find_names`, `pad_names`, `generate_doc`), which is now just a compatibility facade;
`apply_ja_rules.py` has been deleted — use `engine_text --lang ja`.
`zh.normalize` / `ja.normalize(particles=)` also stay as shims.

---

## 6. Explicit non-goals

- **No right-to-left languages** (Arabic, Hebrew, …): there is no game source code, the
  engine's drawing direction cannot be changed, and spacing cannot fix it. `Spacing` has
  three modes and no direction field.
- **No pixel / font-width judgements**: control widths were never measured, see
  [Translation limits](translation-limits.md).
