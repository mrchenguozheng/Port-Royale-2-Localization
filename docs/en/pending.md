# Pending Items

> **Current support scope: GOG English `1.1.2.3` only.** The items below are
> unsupported builds or future directions, not part of the current support scope.

Questions that have no conclusion yet, or where we know how to investigate but haven't. Ordered by "can we act now": earlier items are **known how, just need execution**; later ones **have a direction but no conclusion**.

---

## 1. Steam version: language pack does not take effect after injection (top priority)

**Symptom**: On the Steam English version, `PR2Launcher.exe` can launch the game, but the interface is still English — the language pack is not being substituted in. The same steps work perfectly on the GOG English version.

**Already confirmed**:

- The Steam `PR2.exe` has Valve CEG integrity verification; changing a single byte of the exe triggers
  `Application load error 3:0000065432` — so runtime injection is the only option; the file cannot be modified;
- This project's injection **does not write to the exe**, so in theory CEG should not block it;
- Injection on the Steam version reports no error, but **the text-lookup hook does not take effect** (the UI text is unchanged).

**Not yet investigated, ordered by suspicion**:

1. **The hook's hard-coded offsets do not match.** The current code takes function addresses from offsets in the GOG build of `A2dLib-2.20A.dll`. First compare this DLL's export table / function entry points between the two versions — that directly determines whether "the offsets are wrong".
2. **`A2dLib-2.20A.dll` is stored in a different place.** GOG puts it in the game root; on Steam it may be at the same level or in a subdirectory. The DLL is lazily loaded, so if the module path cannot be resolved, the hook fails.
3. **When CEG runs its self-check.** If CEG has already flagged the process as an "integrity violation" before the injection point, the injected DLL may be silently ignored (rather than crashing).
4. **The Steam version may have an extra DRM layer** (SteamStub / CEG double wrapper), so the process startup path differs from GOG, and the launcher's suspend–inject–resume flow needs to be re-validated.

**Minimal experiment to decide**: On the Steam version, do only one thing — "inject a minimal DLL that prints `PR2TextSource.log`" — and see whether the log gets written. This immediately distinguishes "injection failed" from "injection succeeded but the hook did not hit".

---

## 2. GOG French version has never been verified in-game

The string table for the French version `1.1.2.42` has been extracted as a reference (`references\fr.gog_1.1.2.42.toml`), but it has **never actually been patched into the French game and run through the UI**.

To do: run the same three steps as for the GOG English version (build → deploy to the game directory → launch), focusing on two things:

- Whether injection works (whether the language pack displays);
- The French version has 42 more and 19 fewer strings than the English version; whether the `n` tags and placeholder offsets still line up (`load_toml` already tolerates this kind of version difference, but the hook looks up the table by id, so this needs real testing).

---

## 3. Hook is tied to the game version

The code fetches functions in `A2dLib-2.20A.dll` by fixed offsets. Any change of game version (including the GOG French version, or a future patch) may require relocating the offsets; otherwise nothing works at all.

Long-term approach: switch to **locating by export name / signature** instead of hard-coded offsets; at minimum, record the mapping between the "offset table" and the "version number", so that a version change makes it obvious what needs to be changed.

---

## 4. Entire long Chinese sentences are not displayed

The engine splits words on spaces. A whole run of Han characters with no spaces is treated as one over-wide word, and **over-wide lines are discarded entirely**, not truncated. So occasionally "this entry is completely invisible in the game" while everything looks fine in the editor.

For now we can only test entry by entry in-game. A possible mitigation: provide an offline check that "estimates by widget width", flagging obviously over-long entries first.

---

## 5. Font stitching and glyph coverage

The fonts shipped with the game have no Chinese glyphs, so `fonts\*.TTF` must be replaced; currently `src\tools\font\fontstitch` uses the original Latin font as the base and appends the characters used by the translation from a donor font. Each language has its own `build\fonts\<language>\` (four fonts, about 0.7–1.3 MB), independent of the others. The original glyphs, character widths, kerning and name table stay unchanged.

"Compile language pack" compares automatically: if the translation introduces a new character that the font lacks, it re-stitches that language's four fonts; the cache marker is `build\fonts\<language>\.stitch.json`.

**In-game verification (2026-10-22)**: the main menu displays Chinese correctly, the title font has Chinese glyphs, no anomalies.

---

## 6. Garbled names of old saves (can only be renamed manually)

PR2.exe imports only the ANSI file APIs (`FindFirstFileA` etc.); Chinese characters in file names are mapped byte by byte as Latin-1 and display as `×Ô¶´…`.

- New autosaves have already been changed to ASCII (`Autosave %02u`), so they will no longer be garbled;
- **Existing** save files with Chinese names will still be garbled; just rename them to ASCII names;
- A complete fix would require hooking the engine's small "filename bytes → text" step; the cost is too high, so it is not being done for now.

---

## 7. Leftover `D774` in the original English (handled following the French version)

The English original of `0xd23b7fdf` is:

```
<ts:80>Due to wear and tear, a %1 D774has sunk today on the trade route....
```

The same hash in the French version is:

```
<ts:80>En raison de son mauvais état, un %1 a coulé aujourd'hui alors qu'il était en transit....
```

The French version has no `D774`, and grammatically reads "a %1 sank", so `D774` is a **leftover character / typo** in the English version (most likely an early placeholder that was not cleaned up).

Handling:

- `references\en.gog_1.1.2.3.toml` **stays as-is** (it was extracted verbatim from the exe; do not modify it, so that future re-extractions can be compared);
- The Chinese and Japanese translations both render it as "a %1 sank", without `D774`;
- This is the only entry in the whole table that contains `D774` (confirmed by script).

---

## 8. Copyright notice must be kept verbatim (`0xfc512ea5`)

This entry is a third-party license notice:

```
Uses Miles Sound System, Copyright 1991-2004 by RAD Game Tools, Inc. MPEG Layer-3
playback supplied with the Miles Sound System from RAD Game Tools, Inc. MPEG Layer-3
audio compression technology licensed by Fraunhofer IIS and THOMSON Multimedia.
```

**Do not translate**; keep the English verbatim. Translating this kind of text is meaningless and could also change the meaning of the license notice.

This has been made a hard constraint: the `KEEP_ORIGINAL` table in `compile_pack.py` forces the original English at compile time — whatever the translation says is overridden, and a warning is emitted. To add similar entries later (other third-party notices, trademark lines), just add the hash to this table.


## Adjacent placeholders: which are "given name・surname" and which are format strings

Many strings in the game place two placeholders side by side (`%1 %2`, `%2 %3`). In Chinese/Japanese, a `・` goes between the given name and the surname, but only when those two positions really are given name and surname; if they are "level + name" or "quantity + unit", adding one is wrong.

| hash | Verdict | Notes |
|---|---|---|
| `0xE23F403A–D` | given name・surname (`%2・%3`) | `%1`=level, `%2`=given name, `%3`=surname |
| `0x200D4E11` | given name・surname (`%2・%3`) | Same as above, used to compose the display name |
| `0x28B1F98D` | given name・surname (`%1・%2`) | Opening welcome line; the level is mentioned later, which shows the first two segments are personal names |
| `0xCA6F7276` | given name・surname (`%2・%3`) | In a quest, "someone's name is recruiting heroes" |
| `0xDBCAC2B1` | given name・surname (`%2・%3`) | Letterhead `%1,<n>%2・%3` |

**Still uncertain (left as-is, no `・` added):**

| hash | Content | Why it cannot be decided |
|---|---|---|
| `0xE7270933` | `<gs:TEXTFLUSS_KEINEHOEHE>%1  %2` | Only two numeric slots visible, no context |
| `0xFFDC2433` | `<c>%1  %2` | Same as above |
| `0x08B186EF` | `<r>%1<n>%2   %3` | Same as above; `<r>` is a color tag |
| `0x16656B80` | `%1 %2<g:scripts/intext_herz_800x600.screen>` | Ends with a "heart" icon; the two slots may be numeric values |

### Tag meanings

- `gs:` = graphic script instruction, consumed by the UI renderer, **not translatable text**; it must be kept verbatim, otherwise the line loses its layout or icon.
- `gs:TEXTFLUSS_KEINEHOEHE` is German: `Textfluss` = text flow, `Keine Höhe` = no fixed height, i.e. "text lays itself out by content, with no reserved height". It only affects layout and has no literal meaning to translate.
- `<c>`, `<r>`, `<n>` are color / red / newline respectively; `<g:scripts/…>` references a UI graphic (`intext_herz` being the "heart" icon).

The only way to settle these four as well is to check in-game which screen they appear on and what numbers sit next to them.
