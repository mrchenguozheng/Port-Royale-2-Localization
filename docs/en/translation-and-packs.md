# Translations and language packs

The human-maintained source for translations is `src\translations\<language>.toml`;
`build\PR2Packs\<language>.txt` is its **compiled output**:

```
src/live/zh.toml ──src/tools/pack/compile_pack.py──▶  build/PR2Packs/zh.txt
```

To change a translation, edit `src\translations\`, then recompile the language pack.
If you edit `build\PR2Packs\*.txt` directly, it will be overwritten on the next compile.

---


> **Where `seed/zh.toml` came from**: on 2026-10-21 it was reconstructed from the
> `zh.toml` of that time by **removing every added space** (none left between
> Han characters, around punctuation, or on either side of placeholders), while spacing
> that the original text already carries — em dashes and `<o:…>` — was kept. After the
> reconstruction `apply_zh_rules.py` was run again, and the resulting `zh.toml` was
> **byte-for-byte identical** to the deployed version, so it can be used as the text source.
> It is not "the first version that was hand-written entry by entry back then" — that
> version was never archived separately; if it later turns out that some space was in the
> original text all along, edit `seed/zh.toml` directly and the rules will regenerate it.



## Generate → edit → build

- `src/seed/<language>.toml`: initial translation (locked by default; unlock entry by entry in the editor to change it);
- `src/live/<language>.toml`: working text maintained directly by the editor; saving writes only here;
- the build (`apply_patch`) compiles `live/` directly and never regenerates or overwrites it;
- to regenerate from the initial version, run `apply_zh_rules.py` / `apply_ja_rules.py` manually;
- the old manual review workflow (`zh_review.py`, review markers, page banner, reviewed checkboxes) has been removed entirely.

## Rules split per language

Punctuation/spacing rules are no longer piled into `normalize_text.py`; there is one file per language:

```
src/tools/text/lang_rules/
├─ base.py   shared machinery: space after punctuation, spaces around placeholders, removing spaces around <n>
├─ zh.py     Chinese: full-width punctuation table, half-width→full-width map (, → ，), normalize()
└─ ja.py     Japanese: its own punctuation table (, → 、), particle spacing, normalize(particles=)
```

- `normalize_text.py` is now only a CLI: pick the language → read the toml → call `lang_rules.<language>.normalize()` → write back;
- to add a language: put `<code>.py` in `lang_rules/`, providing `LANG / PUNCT / ASCII / CJK_RX / normalize()`,
  then register it in `REGISTRY` in `lang_rules/__init__.py`;
- languages without dedicated rules can still apply the Chinese rules with `--force`;
- although `・`(U+30FB) and `ー`(U+30FC) fall inside the kana block, they are **not treated as body text** and are never
  split apart (otherwise `%2・%3` and `迭戈・莫扎雷拉` would gain spaces).

## Directory structure

```
src/live/
├─ zh.toml                generated: the result after the rules add spaces; do not edit by hand
└─ ja.toml                Japanese translation (edited directly)
src/orig/
├─ en.gog_1.1.2.3.toml    English original, the baseline (id order follows it)
├─ fr.gog_1.1.2.42.toml   French original
└─ zh.gog_1.1.2.3.toml    Chinese text source: a clean translation with no added spaces
```

`en` / `fr` are **read-only reference originals**; no language pack is generated for them, and
`compile_pack --lang en` returns exit code 2. They stay in the language list for comparison.

One entry per line; the key is the hash:

```toml
"0xd2d0a572" = "萧条"
```

Keys must be double-quoted (a bare key cannot start with a digit). **Do not use `[["0x…"]]` array tables** —
they cannot catch duplicate keys.

---

## Compiling the language pack

```
src\build_translation.bat
```

Compiles the language packs only; equivalent to `python src\tools\pack\compile_pack.py`, except that it also locates Python by itself.

It copies `src\locale.ini` verbatim into `build\PR2Packs\` — that file is a template, not generated output; the DLL relies on it to know which language pack to read, and without it nothing loads at all.

If it would compile 0 entries, it **fails with exit code 1 and writes no file** — a 0-entry pack installed into the game means nothing is localized, and callers only check "is the file there", so an empty file is harder to diagnose than an error.

---

## Language pack format

The compiled output **has no explanatory header of any kind**; the first byte is the first data entry:

```
0x1007ADD4 = 剧本顺利完成
0x100AFA32 = %1，<n>我们的教堂需要持续修缮，……
```

| Notation | Meaning |
|---|---|
| `0xHASH = text` | one hash per line, hash in uppercase |
| `<n>` | the engine's line-break tag |
| `<o:0x…>…</o>` | color markup; after the colon is an ARGB color |
| `<f:fonts\…>` | inline font specification |
| `%1`, `@D$EndDate$` | placeholders; count and kind must match the original |
| `\|` | **legacy form, deprecated**: still converted to `<n>` as a fallback at compile time, but do not write it in source files any more |

The parser skips lines starting with `#` and `;`, so hand-written comments are not treated as data —
but **do not rely on this**: the language pack is compiled output and they will be gone on the next compile. Put explanations here instead.

---

## Layout rules (measured)

- **The engine tokenizes on spaces.** Chinese naturally does not use spaces as boundaries, so an entire run of
  Han characters together with punctuation is treated as a single over-wide word, and an over-wide line is
  **dropped entirely = not displayed at all**, not truncated.
  Every UI control has a different width, and the tool **does not estimate width**; it can only be measured screen by screen.
- Tags (`<n>`, `<o:0x…>`, `<f:fonts\…>`) are **kept as-is**; do not delete them.
- Not a single placeholder may be missing, and **do not add** new `<n>` — line breaks go only where the original
  already has `<n>` (one-to-one with the paragraphing of the English/French originals).

---

## Spacing conventions (for languages such as Chinese and Japanese that do not separate words with spaces)

This section is a **requirement of how the game engine renders text**, not a typographic preference: the engine splits
words on spaces, and a word that is too long makes it drop the whole line; placeholders must be recognizable on their
own, so they need to be separated on both sides too.
So for any language in which "words are not normally written with spaces between them", the translation must add
half-width spaces according to the rules below.

**There are two trigger conditions**: the punctuation is **full-width**, and words are **not normally written with
spaces between them**. Chinese and Japanese satisfy both, so they follow the rules below.

**Korean does not trigger by default**: Korean has 띄어쓰기 (word spacing); words are already written with spaces
between them, and tokenization works the same as in English; punctuation is also **half-width ASCII**
(`.` `,` `?` `!` `:`), not full-width.
So Korean needs no spaces added around punctuation; keeping the existing inter-word spaces is enough. References:
[Spaces and full width punctuation in Korean (W3C discussion)](https://lists.w3.org/Archives/Public/www-archive/2020Sep/0002.html),
[Word Segmentation in Korean (Stanford)](https://nlp.stanford.edu/fsnlp/korean.html).

**But if a language does use full-width punctuation** (including old-style full-width Korean, or a new language that
appears later), handle it with the same set of rules — the rules look at "full-width punctuation", not at nationality.

**Punctuation**

- after a single punctuation mark (`，。、；：！？…・` etc.) add **one** half-width space;
- paired punctuation (`「」『』“”《》【】（）` etc.) gets one on the **outside** of each: before the opening mark,
  after the closing mark (`日志的 「成就」 里`, not `日志的「 成就 」里`);
- between adjacent punctuation marks leave only **one** space; a run of punctuation stays tight (`《航海条例》。` does not
  become `《航海条例》 。`);
- **no space at the end of a paragraph**, and none at the start either;
- the middle dot `·` (as in the name Janet · Smith) **does not participate** in the rules and stays tight.

Japanese uses its own punctuation set: single marks `、。！？…・：；～—`, pairs `「」『』（）［］【】〈〉〔〕`.

**Placeholders**

- for `%1`, `%10`, `%02u`, `%s` and `@X$variable$` (such as `@T$Town$`, `@D$EndDate$`), whenever one side is directly
  adjacent to a Chinese/Japanese character or punctuation mark, add one half-width space on that side:
  `可在 %3 建造`, `赶往 @T$TOWN$ ，`;
- multiple spaces are collapsed into one; consecutive spaces never appear.

**Japanese particles (optional)**

A half-width space may also be added after particles in the middle of a Japanese sentence (`市场に 来てくれれば`), again
for the engine's tokenization. The rules are conservative and only handle "kanji/katakana + particle + kanji/katakana":

- particle list: `から まで より など ほど ばかり だけ しか こそ さえ でも って ので のに けど`,
  plus the single characters `は が を に で と も へ や か ね よ` (**「の」 excluded**: splitting a possessive
  like `木材の需要` would look too choppy);
- a space is added only when the particle is immediately followed by kanji/katakana/opening bracket; **if a hiragana
  follows, always skip** (to avoid cutting off word endings such as 「について」「として」「ません」);
- if punctuation or the end of the sentence follows immediately, leave it alone, to avoid spaces before punctuation
  such as 「船か 。」.

How the decision is made (chosen automatically):

1. if **Janome** or **fugashi** is installed, use morphological analysis and add spaces only for
   "noun/pronoun/numeral + particle", skipping fixed expressions such as `について` `として` `によって` `という`;
2. if neither is available, fall back to a regex (kanji/katakana + particle + kanji/katakana).

Toggle: `python src\tools\text\normalize_text.py --lang ja --particles`.

**Other**

- **no spaces** on either side of the `<n>` line-break tag (`…。 <n>下一段` is normalized to `…。<n>下一段`);
- these rules are applied in bulk by the translation-processing scripts (`|`→`<n>`, punctuation spacing, placeholder
  spacing); a new language just needs to follow the same conventions.

---

## Honorific systems and "over-politeness"

In languages that have an honorific system, the mistake most easily made in translation is not mistranslating but
**raising the register**. This section records the problem, the criteria, and the current conventions.

**Which languages have honorific systems**

| Language | System | Manifestation |
|---|---|---|
| Japanese | 尊敬語・謙譲語・丁寧語・美化語 | `いらっしゃる` / `差し上げる` / `です・ます` / `お〜` |
| Korean | 높임법 (honorific system) | `하십시오체` / `해요체` / `반말`, plus humble verbs such as `드리다`, `모시다` |
| Chinese | no grammatical honorifics, but polite vocabulary | `您`, `请`, `贵`, `光临`, `惠顾`, `敬告` |
| English / French / German | **no** honorific system | only personal politeness: French `vous`/`tu`, German `Sie`/`du` |

**How polite the original really is**

The original of this game is German (`Sie`); the English translation uses a neutral `you` plus imperatives, and the
French translation uses `vous` throughout.
`vous` / `Sie` is **politeness in how a person is addressed**, not a level of honorifics — it has no "humbling" dimension.
So the equivalent of `you` / `vous` is Japanese **です・ます**, and nothing needs to change there.

**How over-politeness arises**

- translating "I give you" as `差し上げます` (a humble form that raises the player by one notch, where the original is
  just `I will give you` / `je vous offre`);
- translating "you will receive" as `お受け取りになります` (the original `you will receive` is a plain statement);
- writing narrative sentences and system notifications in polite form too, or addressing the player with `お持ちです`,
  `お越しください`;
- adding closing modifiers the original does not have, for example 「わが国も深く感謝しています」;
- the reverse error exists as well: pirates' and drunkards' lines are crude by nature; raising them to polite form to
  follow `vous` would ring false.

**Conventions**

1. **NPCs speaking to the player** (governors, merchants, financial officers, letters) → です・ます,
   with **no humble forms**, unless the original itself is explicitly self-deprecating (this game has no such case);
2. **pirates, drunkards, rough characters** → plain form (`だ`・`ぞ`・`な`); do not raise it just because the French uses `vous`;
3. **event notifications, UI prompts, system congratulations** → neutral register or です・ます, but **do not use
   honorific address for the player**; notifications use the third-person past tense;
4. **do not add** honorific modifiers, thanks, or pleasantries that the original does not have;
5. Chinese: `您` aligns with the original's `vous`; within the same character **do not switch between 「您」 and 「你」**;
   polite vocabulary (`光临`, `惠顾`) is used only in merchants' sales pitches;
6. Korean (not started yet): first settle on one of `해요체` or `하십시오체` and apply it consistently, and do not mix
   them for the same NPC; humble verbs `드리다`/`모시다` only where the original really is self-deprecating.

**How to check**

```bash
python src\tools\analysis\speaker_audit.py
```

It regenerates [Speaker tiers](speaker-tiers.md) (with A/B/C/N tiers) and a per-entry
[speaker-audit.csv](../csv/analysis/speaker-audit.csv), in which the "register to review" column lists entries where
the Japanese contains `差し上げ` / `お受け取り` / `お持ち` / `お越し` / `申し上げ` / `いたします` while the English
original is a plain statement.

Severity varies: `差し上げます` and `お受け取りになります` most need fixing;
`お持ちです` and `お越しください` are ordinary honorifics, commensurate with `vous`, and can stay;
`おめでとうございます` is a system congratulation and not over the line.

**Current leftovers (2026-10-21)**

- **26 entries** awaiting review; the list is in the `register to review` column of
  [speaker-audit.csv](../csv/analysis/speaker-audit.csv);
- typical cases: `0x13601073` (`…a barque` → `バークを差し上げます`),
  `0xf94c02c2` (`you will receive` → `お受け取りになります`),
  `0x171746e9`, `0xfbb36ec1`, `0xfdaf6463` (`差し上げます` in the land-grant texts);
- **not changed yet**; they will be handled in one pass once the tone baseline is confirmed, to avoid changing things
  and then changing them back.

---

## Validation

```
python src\tools\translate.py status              # progress
python src\tools\translate.py export --out x.jsonl # export entries awaiting translation
python src\tools\translate.py check x.jsonl        # validate
```

All three subcommands accept `--lang <code>` and by default operate on the first editable language under
`translations\`.

`check` catches these classes of problem:

| Check | Meaning |
|---|---|
| Placeholders | `@D$EndDate$`, `%1` must match the original in **kind and count** |
| Tag outline | the translation **must not** add any `<n>` / `<o>` / `<f>` / `<c>` / `<t>` tag |
| Untranslated | placeholder text of the form `0x<id> \| <English original>` |

Line breaks may only go where the original already has `<n>`. When a new line is naturally wanted, let the renderer
wrap automatically by width; do not insert `<n>` by hand.

---

## No tamper validation for en / fr

`translate.load_toml()` itself reads en / fr from `src\references\en.gog_1.1.2.3.toml` and `fr.gog_1.1.2.42.toml`, so
validating the merged result against them always comes out equal. Real validation would need an independent baseline
outside the repository; that is a separate matter.

---

## Adding a language

Three steps, with no need to touch C++ or the DLL at any point. For the complete from-scratch
workflow, see [New language](new-language.md).

1. **Create the translation file** `src\translations\<code>.toml`.

   One command does it — copy an original as a template, then change the right-hand side of each entry into the translation:

   ```
   python src\tools\pack\new_lang.py --new-lang <code>
   ```

   It copies `references\en.gog_1.1.2.3.toml` (add `--from fr` to start from French instead), and in the generated file
   the right-hand side of every line is the original text, i.e. the "untranslated" state.
   Existing files are not overwritten.

   Writing it by hand works too; the format is one entry per line:

   ```toml
   "0xd2d0a572" = "Vegetating"
   ```

   Writing only the entries you actually intend to translate is enough — the rest automatically display English. But
   **the number and order of entries must match `references\en.gog_1.1.2.3.toml` exactly**, because alignment is by
   position. If any are missing or extra, `compile_pack.py` reports an error.

   `<code>` is the filename; it becomes the filename in the language pack and the `language=` value in `locale.ini`
   directly, and is also used as the field name when merging — so do not use any other separator.

2. **Start the workbench** with `start.bat`, select the new language on the install page →
   "Generate" → "Deploy".

   The language list comes from `src/live/*.toml`; a new language can also be created directly from the translation
   editing page by clicking ＋.

3. **Switch language** in the "Language" dropdown on the install page, then click "Set as game language" —
   **the dropdown itself does not touch any files**; "Launch game (injected)" only launches with the selected
   language and does not write `locale.ini`. Writing to disk happens only on "Set as game language".

Command-line equivalents:

```
python src\tools\pack\compile_pack.py --lang <code>
python src\tools\translate.py status --lang <code>
```

Language codes have no formal requirements; `zh` / `zh-CN` / `de` / `pt-BR` all work, as long as they **match the toml filename**.

---

## Rebuilding all originals (rarely used)

`src\tools\pack\new_lang.py` with no arguments regenerates the three files en / fr / zh from the English and French
originals; use it only on first setup or when switching game versions.
Its data source, `editor\data\editor-data.json`, is not in the repository.

**Do not run it for everyday translation edits** — it will overwrite your changes with old data.

---

Related docs: [Injection](injection.md) · [Build and install](build-and-install.md) · [Architecture and refactoring](architecture.md)

### Translation editing area (contenteditable)

The translation area no longer uses a "transparent textarea + highlight overlay" but `contenteditable`: spaces are
rendered directly as `<span class="hl-sp">`, so there is no two-layer alignment problem. During Chinese IME composition
(compositionstart→end) the DOM is not re-rendered; it is re-laid-out once after composition ends and the caret is
restored, so the candidate window is not interrupted.

**Middle dot in name placeholders**: in the chronicle, `%1 %2 %3` is usually "rank / given name / surname",
so write only `%1 %2・%3` (space after the rank, `・` between given name and surname);
for the two-part form `%1 %2`, if it means "rank + full name", use a space and do not write `%1・%2`,
otherwise you get 「见习水手·巴尔塔萨·马尔伯夫」.

### Placeholder joining rules (per hash, no bulk replacement)

`%1 %2` may mean "rank + full name" or "given name + surname"; bulk replacement is bound to get one of them wrong.
So rules are now recorded per hash:

```toml
# src/live/placeholder_roles/zh.toml
["0x338a357f"]
rules = [
  { pair = ["1", "2"], sep = " ", note = "等级 + 全名" },
]
```

Tool: `python src/tools/placeholder_roles.py`

- `--report --lang zh|ja`: scans all adjacent `%N %N` and exports
  `docs/csv/analysis/占位符语义.<lang>.csv` (hash, current separator, inferred suggestion, English context) for human review;
- `--check`: validates against the rules already recorded for that language and lists separators that do not match;
- `--fix`: changes **only** entries with explicit rules; everything else is left alone;
- rules are kept separately per language: `placeholder_roles/zh.toml`, `placeholder_roles/ja.toml`; default `--lang zh`.

To add a rule: find that parameter pair in the CSV → add a line to the toml → `--check` → (if needed) `--fix`
→ regenerate with `apply_zh_rules.py`.

### Prefer spaces for layout; do not change words or sentences

The game breaks lines at spaces, and the detail box has a fixed height. For display problems such as "the top is
clipped and only the last line remains", the fix is to **add a few spaces at suitable places** so the line breaks
earlier, not to delete characters or shorten the translation.

- spaces are a layout device and do not change meaning; the translation content follows the text source;
- when the line count needs to be reduced, prefer adding spaces at clause boundaries and before long words;
- do not rewrite or trim the translation just to make it fit the box.

### Placeholder and space hints in the editor

Above each translation there is an info bar:

- **Placeholders**: lists the `%1` / `@T$Town$` etc. that appear in the English of the current entry, with their
  meanings (`%N` is labeled "rank/title, given name, surname, full name" from English context; `@g$…$` is labeled
  "amount", etc.);
  - in the body, placeholders render as draggable pills that show the meaning directly inside (e.g. `@g$TotalPrice$ 金额`);
  the meaning is rendered with CSS `::after` and never enters the body text or saved content;
- dragging a pill to the target position performs the move;
  - placeholders cannot be deleted: if deleted they are automatically put back (the count follows the English original);
  - the info bar only shows how many of each placeholder are required (`×2`) and the meaning; the insert/remove buttons are gone;
  - ones present in the translation but not in the original are marked red as "not in original" and can be removed;
- **Spaces**: only shows how many more there are than in the clean translation (layout spaces added after punctuation),
  without listing positions;
- **Markup**: the meaning of layout tags such as `<n>`.

API: `/api/entry-info?lang=zh&id=<hash>`.

### Clean text source

Each language under `src/orig/` can have a clean translation **without layout spaces**:

- `zh.gog_1.1.2.3.toml`: Chinese (the source from which `live/zh.toml` is generated);
- `ja.toml`: Japanese (obtained by stripping layout spaces from `live/ja.toml`).

The "Spaces: N more" in the editor's info bar is derived by comparing the current translation against this clean text.

### Japanese: clean source → rule-generated

```powershell
python src/tools/text/apply_ja_rules.py          # compare only; prints the number of differing entries and samples
python src/tools/text/apply_ja_rules.py --write  # write to live/ja.toml
```

The rules come from `lang_rules/ja.py`: punctuation normalization, spaces on both sides of placeholders, spaces after
particles (morphological analysis when janome/fugashi is installed, regex fallback otherwise).
By default no file is written, to avoid overwriting manual layout; add `--write` once the differences look acceptable.

### Placeholder counts must match one by one

- the info bar shows counts (e.g. `×2`); placeholders whose count differs between the original and the translation are
  marked red, with the notice "placeholder count mismatch";
- on save the server enforces validation: if `/api/patch` finds any placeholder used more or fewer times, it rejects
  the whole batch and returns the specific entries and counts (N in the original / M in the translation), without
  writing the file.

### Undo and restore clean original

Two buttons on the right of the info bar:

- **Undo**: undoes the last edit of the current entry (up to 20 steps are kept, in memory);
- **Restore clean original**: replaces the current translation with the clean text from `orig/` (`/api/clean`);
  after restoring it is still unsaved, and can be undone or saved again;

When there are unsaved changes, paging, jumping, switching language, or switching to "Install and launch" first asks
for confirmation; only choosing to save lets you leave. Closing or refreshing the page also prompts. If the translation
is identical to what was just loaded it counts as unmodified and is not blocked.

Note: the clean text itself carries no layout spaces; after restoring, if you want to keep the layout, re-apply the
rules of the corresponding language.

### Per-hash terminology exceptions

When the terminology check reports a false positive (for example, in `0x28b1f98d` "Ship's Boy" is a runtime
placeholder in the translation, so it should not require 「见习水手」 to appear), you can make an exception for it in
the editor:

- the info bar shows "Term: Ship's Boy should be 「见习水手」" and an "Ignore" button;
- clicking "Ignore" writes to `glossary/hash_rules.toml` and applies to that one entry only;
- ignored ones show "Ignored: Ship's Boy" and a "Restore" button;
- API: `GET /api/hash-rules?id=`, `POST /api/hash-rule {id, term, skip}`.

`0x28b1f98d` has had "Ship's Boy" ignored under this rule.

### Saving takes effect immediately

- clicking save in the editor writes directly to `live/`; there is no separate review step;
- `orig/` holds only clean text (no layout spaces); all generated output is produced by the rules.

### Unified check before committing

```powershell
check.bat                 # or python src/tools/check.py
```

Runs in order: cross-module reference check → rule unit tests (`tests/`) → generated-artifact consistency
(`apply_zh_rules.py --check`).

### Division of labor between the three directories

```
src/orig/   English and French original references: strictly read-only, never written by any process
src/seed/   initial translations (machine/AI/human first drafts): locked by default; editable only after unlocking entry by entry in the editor
src/live/   text maintained directly by the editor: saving writes here, and the build reads only from here
```

- editor saves write only to `live/`, and no longer touch `seed/`;
- the "initial version" text is always shown below the translation box for comparison with the current working text;
  when the content differs (ignoring spaces), a highlighted vertical bar appears on the left;
- "Unlock editing" at the top right of the initial-version block opens the initial-version dialog: read-only by default;
  after clicking "Unlock editing" and confirming, only that one entry can be edited, and it re-locks automatically after
  saving or closing (the unlocked state is not remembered);
- "Restore clean original" uses the initial-version text and overwrites the current working text (undoable);
- `apply_zh_rules.py` can still be run manually to generate `live/zh.toml` from `seed/zh.toml`, but it is not a build step.

### Rule trace (visualization)

The "Rules" button in the info bar opens a dialog that shows this translation stage by stage:

```
初版            → 标点规范化 → 连词后空格 → 人名/城镇名空格 → 当前译文
```

- each stage highlights only the parts that changed relative to the previous stage;
- API: `/api/rule-trace?lang=&id=`;
- currently Chinese shows 4 stages; other languages show 初版 → 规范化 → 当前译文
  (initial → normalized → current);
- the "match annotations" at the end color-code the characters changed by the rules: orange = punctuation/placeholder
  spaces, blue = conjunctions, green = person/town names; when the current translation differs from the
  rule-generated one, it notes that the annotations refer to the generated result.

### Space coloring in the body (L1)

The editor does not highlight spaces by default; "space coloring" has been removed (the effect was unreliable).
To inspect how the rules were applied, open the "Rules" dialog in the info bar and view stage by stage.

### Manually changing placeholder meanings

- the "Edit" button after a placeholder pill in the info bar: opens an input box to change that placeholder's meaning
  **for the current hash**;
- saved to `glossary/placeholder_meanings.toml`, one record per language + hash + placeholder;
  the meaning may be an empty string (meaning deliberately blank, no more automatic inference);
  when the editor opens an entry it also pins the meanings of the placeholders used in that entry, so they do not
  affect one another;
- changes affect display only, not the translation or compilation; they can be changed repeatedly.
