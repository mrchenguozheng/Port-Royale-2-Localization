# Translation Limits: Why a Translation Is Bound to Have Flaws

This document records the problems that are **known and cannot be fully eliminated with tools**, and how far we actually verified things.
The purpose is not to disclaim responsibility, but to let those who come later know which parts can be trusted and which must be checked in the running game.

## 1. Three flaws that cannot be eliminated

### 1.1 Speaker and tone: no authoritative data on "who is speaking"

A language pack contains only `hash = text`. Which NPC speaks a given line, and on which screen, is **not in the language pack**.
Only two categories can be pinned down:

- **Grade A, 6 entries**: the text itself carries a signature / self-reference / title (e.g. `…, Governor of %5`);
- **Viceroy voice lines, 35 entries**: in the pointer table in `PR2.exe`, this batch of voice lines corresponds one-to-one with `ID_NPC_VICEROY_*` (see [voice mapping](../语音映射.md)).

The remaining 3,500+ entries can only be grouped by **topic keyword**, and "topic ≠ speaker":
`On behalf of my nation, I would like to thank you for destroying a convoy of the notorious pirate…`
contains `pirate`, yet the speaker is the governor. Therefore:

- tone cannot be changed in bulk by category ([Tone proposals](tone-proposal.md) already makes this point);
- the 180 template families were checked for stylistic consistency (0 families mixed), which shows that templates within a family do not contradict each other,
  but "which tone an entire category should use" still requires human judgment.

### 1.2 Layout: the engine splits words on spaces, widget widths unknown

The engine's word-splitting rules are described in the "space convention" section of [Translations and language packs](translation-and-packs.md):
Chinese and Japanese have no spaces between words, so the whole string is treated as one over-wide token, and **an over-wide line is dropped entirely (not truncated)**.
We add spaces according to those rules, but residual risks remain:

- every widget has a different width, and the tool **cannot know in advance** how wide the widget holding a given line will be;
- short labels (`Corn` → `とうもろこし`, `Brig` → `ブリッグ`, personal names → katakana) are inherently wider than English,
  and these are exactly the kind most likely to appear in narrow buttons or lists;
- tags and `<n>` line-break positions can only follow the original text; they must not be added or removed at will.

A rough width check with the game font (`src/tools/analysis/width_check.py`, using "translation width ÷ English width" in the same font as a proxy metric):

| Language | Comparable entries | Median width ratio | ≥1.5× | ≥2.0× | Single token ≥200px |
|---|---|---|---|---|---|
| Japanese | 3,421 | 0.85 | 171 | 10 | 415 |
| Chinese | 3,421 | 0.64 | 11 | 2 | 688 |

Conclusion: **overall, Chinese and Japanese are not wider than English** (median 0.85 / 0.64). The real risk is concentrated in
**short labels, proper nouns, and units** (such as `%1 (%2 kn)` → `%1 （ %2 ノット）`).
Per entry, see [宽度粗查-ja.csv](../csv/analysis/宽度粗查-ja.csv) and [宽度粗查-zh.csv](../csv/analysis/宽度粗查-zh.csv).

### 1.3 Meaning: corroborated only between English and French, and still misread sometimes

- the source text itself has typos: `D774` (the English version has the date wrong; the French version is correct — see [Pending items](pending.md));
- placeholder meanings can be misread: the `%1` in `0xfbb36ec1` was once taken in the Chinese translation as "number of towns",
  but it is actually a town name (now corrected against the English and French originals);
- version differences: French `1.1.2.42` is newer than English `1.1.2.3`; 42 entries appear only in French and 19 only in English,
  so cross-referencing can only compare the intersection of hashes;
- culture-specific terms (`Letter of Marque`, `buccaneer`, `viceroy`) require the translator to set a tone;
  we followed the convention used in historical scholarship (私掠免许状 / バッカニア / 副王), but that is still a choice, not the only answer.

## 2. How far we actually verified

| Item | Coverage | Method |
|---|---|---|
| Placeholders / `<n>` / tag sequences | **100%** (3,548 entries) | `compile_pack`, `check_breaks`, 0 errors |
| Font glyph coverage | Full | `subset_fonts` uses fontstitch to re-stitch automatically based on the characters used (currently 2,922 characters) |
| Tone consistency (within the same template) | 180 families | Template-family comparison, 0 families mixed |
| Width risk | Full (proxy metric) | `width_check.py`, not real widget widths |
| **In-game rendering** | **333 / 3,548 = 9.4%** | `ResolveByHash`/`Add` logs from the injected DLL (`_logs_1843/*.log`) |
| Dialogue coherence | Cannot be verified | Requires the engine's dialogue order, which is not in the language pack |

That **9.4%** is important: it is the number of hashes **actually requested** during the few game sessions we ran.
The remaining 90% of the text has only passed static validation and has never been displayed once in the game.

## In-game observations

### 2026-10-21: Chinese layout improvement (player feedback)

- **Observation**: the Chinese build lays out better in the game than before; the screens we spot-checked **had no entirely blank lines**
  (i.e. cases where the engine dropped an over-wide token);
- **Possibly related changes** (only coincident in time, no causal verification):
  1. unified the half-width punctuation (`,` `;` `:` `!` `?`) in 120 Chinese entries to full width — previously no space was inserted after an English comma,
     so it easily stuck to the neighbouring characters and formed a single token;
  2. date format strings and placeholder spacing rules (`DATE_FORMAT_IDS`), so that strings like `1600 年 4月 1 日` do not get broken up by spaces;
  3. pure format strings (`%1 / %2` etc.) forced back to English, no longer translated into strings containing Han characters;
  4. automatic font re-stitching (fontstitch), so newly added characters do not show as blank due to missing glyphs
     (see [Fonts and distribution](fonts-and-distribution.md)).
- **This still cannot count as full verification**: the injection logs contain only 333 / 3,548 hashes (9.4%) that were actually requested,
  so "no blanks seen" only covers the screens actually played.

**Short labels we recommend spot-checking** (all 11 Chinese entries with a width ratio ≥1.5, the ones most likely to land in narrow widgets):

| hash | English | Chinese | Width ratio |
|---|---|---|---|
| `0x24646e0d` | Brig | 双桅横帆船 | 2.65 |
| `0xff0dd628` | `%1 (%2 kn)` | `%1 （ %2 结点）` | 2.04 |
| `0x1ac38a65` | `%1. %2. %3` | `%3年%2%1日` | 1.99 |
| `0xfc517063` | Piet | 皮耶特 | 1.63 |
| `0xfc517067` | Dirk | 迪尔克 | 1.58 |
| `0xfc5171bf` | Luis | 路易斯 | 1.58 |
| `0xc77f4c7c` | Biloxi | 比洛克西 | 1.54 |
| `0xfc51a0f3` | Elvira | 埃尔维拉 | 1.53 |
| `0xd3e8c706` | `%1: Fire` | `%1 ： 起火` | 1.52 |
| `0xcf572275` | Ruiz | 鲁伊斯 | 1.51 |
| `0xfc51a0f6` | Olivia | 奥利维亚 | 1.50 |

Most of these are ship types and Western personal names; their widgets are usually wide, so they are "worth a look", not "certainly a problem".
The same rule applies to Japanese (median width ratio 0.85; those at ≥1.5× are mostly katakana personal names), and we have not received similar in-game feedback for it yet.

### Inter-word spacing (Chinese)

After the "layout improvement" above, clipping appeared again (in the right-hand column of the scenario selection panel). The cause is that sentences still contain long runs of
Han characters without spaces; the engine can only wrap at spaces, so anything beyond the widget gets clipped. The fix is not more full-width punctuation
but **inserting spaces word by word**:

- Tool: `src/tools/text/space_words.py`, which by default uses the **spaCy + zh_core_web_sm** tokenizer
  (actively maintained, handles OOV better than jieba; personal names containing an interpunct are kept in one piece). jieba is only a fallback;
- spaCy requires Python 3.11 (its dependencies have no wheels for 3.14 yet); point to that interpreter with the environment variable
  `PR2_SPACY_PYTHON`. For installation, see the `space_words.py` section of [Build and install](build-and-install.md);
- only entries with a longest Han-character run ≥ 12 and a widest token ≥ 180px are processed; short labels, buttons, and personal names are left alone;
- words are grouped by target width (default 120px), and spaces are added **only between groups**, so a sentence usually gains just 1–5 spaces;
- applied to 842 Chinese entries (per-entry before/after widths are in [space-words-zh.csv](../csv/generated/space-words-zh.csv)).

It solves the problem of "a long run of Han characters cannot wrap"; it does not solve "the widget itself is too narrow" — that can only be addressed by changing the length of the text.

## 3. Can we automate a playthrough, or hook the data?

- **Automating gameplay**: not realistic. The game runs in real time; triggering every hash would require fully completing several routes,
  and pure input simulation (clicks and keystrokes) is also slow and fragile, and random events would interrupt it.
- **Hooking the data**: feasible, and already under way (see [Injection](injection.md)). The existing DLL hooks `CScreenStrings::ResolveByHash`
  and `CStringManager::Add`; the log shows the hash, the buffer capacity (`zhlen`/`cap`), and the original text.
  To really determine whether a line **breaks the layout**, another hook is needed at the point where text is drawn,
  recording the **widget rectangle** and the **measured text width**; the data can then be collected during normal play — no playthrough required,
  but every screen must be seen at least once.

  The effort this path involves: disassemble to locate the text-drawing function → record `rect`/`GetTextExtent` → write to disk.
  Compared with editing copy, this is the more worthwhile direction, because it yields the fact of which entry overflows on which screen.

## 4. Known specific flaws (exceptions not counted in the statistics)

| Type | Example | Handling |
|---|---|---|
| Source typo | `D774` date | Left as-is; the translation is corrected by meaning, recorded in [Pending](pending.md) |
| Placeholder misread | `%1` in `0xfbb36ec1` | Corrected back to match the English and French originals |
| Signature format | `%1 、 %2 の副王` in `0x03fb5c6a` | Parentheses suggested, but **we decided not to change it in this round** |
| Uncertain tone | 111 entries in the pirate/tavern category are not this character's lines | No bulk change; only manually confirm the 53 first-person entries |
| Width risk | 171 Japanese short labels at ≥1.5× width | Not handled entry by entry; see the rough-check CSV |

## 5. Conclusion

- **What can be guaranteed mechanically**: placeholders, tags, fonts, and tone consistency within the same template;
- **What cannot be guaranteed mechanically**: speaker, widget layout, and semantic details of the source text;
- **Suggested acceptance**: start from the 9.4% in-game coverage; take a close look at the short labels at ≥1.5× in the "rough width check"
  and the Grade A / Viceroy entries (6 + 35) in [Tone proposals](tone-proposal.md), and accept the rest as they are;
- To make layout verification real, the next step should be extending the DLL to record widget rectangles and measured widths, rather than continuing to edit copy.
