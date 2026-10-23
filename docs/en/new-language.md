# New Language: Complete Workflow (From Scratch to In-Game)

Work through these steps in order; each one has a checkpoint. The examples add `de`
(German); for Chinese, substitute `zh`.

> Only want to change the existing Chinese translation? Skip the presets configuration
> in steps 3 and 4; you still need the original fonts from step 2 and the donor from
> step 3.

---

## 0. Set Up the Environment

You need:

- Windows with the game installed;
- Python 3.11+;
- the project source;
- the font files used in steps 2 and 3.

```bash
cd pr2-localization
```

---

## 1. Start the Workbench

Double-click `start.bat`; the browser opens the install page (default
`http://127.0.0.1:8777/install`). At the top of the install page is the
**Install Wizard**: after you pick the target language, it shows status for each
section in turn — 1 Prepare the game directory → 2 Prepare fonts →
3 Translate content → 4 Build → 5 Install and launch — and you can click the
corresponding button directly.

**Check**: the page opens and has two tabs at the top, "Translation Editor" and
"Install & Launch".

---

## 2. Export the Game's Original Fonts

`assets/fonts/original/` is not in the repository, so export it first:

```bash
python src/tools/font/extract_fonts.py --game-dir "<game directory>" --out assets/fonts/original
```

**Check**: four files appear in the directory:

```
ARIAL.TTF  ELGRECO_.TTF  Tiepolo_black.ttf  Tiepolo_bold.ttf
```

---

## 3. Prepare Donor Fonts

Font stitching means "the original Latin fonts + donor Chinese/Japanese fonts".

- Install Chinese/Japanese fonts (Microsoft YaHei, STZhongsong, Source Han Serif, Noto Serif JP, etc.);
- Creating a new language automatically generates `presets/<code>.toml`; then change
  `donor_file` for the language;
- one config per language, independent of one another.

Check what is missing:

```bash
python src/tools/font/subset_fonts.py --check
```

**Check**: the output reads `字体缝合前置条件齐全。` (all font-stitching
prerequisites are present).

If it reports that fontTools is missing:

```bash
python -m pip install fonttools
```

---

## 4. Create a New Language

On the **Translation Editor** page:

1. Click **＋** next to the language dropdown;
2. Enter a language code (e.g. `de`);
3. Pick an existing language as the template;
4. Click **Create**.

This generates:

```
src/live/de.toml
```

(New languages currently only create the `live` file automatically; the initial
`seed` version is not generated, so copy one by hand from the template language to
`src/seed/de.toml` if you need it.)

**Check**: `de` appears in the language dropdown and the list can be paged.

---

## 5. Check the New Language's Donor (Fonts)

When a language is created, `src/tools/font/fontstitch/presets/de.toml` is generated
automatically:

- its contents use the **template language's** presets file as the template; if the
  template has no presets, `zh` is used;
- if the presets directory does not exist, copy it from `presets.example.toml` first;
- one file per language, independent of one another; an existing `de.toml` is not
  overwritten.

The structure is uniform:

```toml
[[pair]]
game_file = "ARIAL.TTF"
donor_file = "%WINDIR%\\Fonts\\msyh.ttc"
donor_index = 0

[[supplement]]
game_file = "ELGRECO_.TTF"
donor_file = "%WINDIR%\\Fonts\\STZHONGS.TTF"

[fallback]
donor_file = "%WINDIR%\\Fonts\\NotoSansJP-VF.ttf"
```

Key points:

- **one `presets/<language>.toml` per language**;
- the donor must be TrueType (`glyf`);
- the donor's UPM must match the game font's: Arial 2048, ElGreco/Tiepolo 1000;
- for languages other than Chinese, the automatically copied Chinese donor may not
  cover the new language's character set, so replace it with a donor for that language.

**Check**: `python src/tools/font/subset_fonts.py --check` no longer reports a missing
donor.

---

## 6. Translate

Edit entries one by one in the editor, then press `Ctrl+S` or click **Save**. Saving
writes directly to `src/live/de.toml`.

**Check**: the translation is still there after refreshing the page; the counters at
the bottom are correct.

---

## 7. Stitch the Fonts

```bash
python src/tools/font/subset_fonts.py --lang de --force
```

**Check**: the log shows

```
de：N 个用字
   ARIAL.TTF
   ...
字体已处理：de
```

and all four TTFs under `build/fonts/de/` have been updated.

If glyphs are missing, the log lists `U+XXXX`: switch the donor or add a
`supplement`, then rerun.

---

## 8. Build the Language Pack and Deploy

Optional: give the language pack a display name and GUI language:

```toml
# src/packs/de.toml
alias = "Deutsch"
gui = "de"
min_runtime = 1
```

`compile_pack.py` writes these as `# pack-meta` at the start of the pack. Without
`gui`, the GUI follows the Windows UI language; without `alias`, the list shows the
code.

Install page, **Install & Launch**:

1. Select `de`;
2. Click **Compile language pack**;
3. Click **Deploy to game directory**.

Or from the command line:

```bash
python src/tools/pack/apply_patch.py --langs de --game-dir "<game directory>"
```

**Check**: the log shows that `PR2Packs\de.txt` was copied, the fonts were copied to
`fonts/de/`, and `locale.ini` points to `de`.

---

## 9. Launch and Verify

On the install page click **Launch game (injected)**, or run `PR2Launcher.exe` in the
game directory.

Check:

- the main menu text;
- the settings menu;
- whether the title font has glyphs;
- whether long text has blank gaps where characters are missing.

**Check**: interface text is readable, there are no blank boxes, and the title font
looks normal.

---

## 10. Common Problems

| Symptom | Cause / fix |
|---|---|
| New language is entirely blank | No presets section for the language (`[language]`) was configured, so the fonts were not stitched; add the section and rerun step 7 |
| A few characters are blank | The donor lacks glyphs; add a `supplement` or switch to a donor with fuller coverage |
| The font reports a UPM mismatch | The donor and the game font have different UPM; switch donors or scale the donor first |
| Chinese is fine but the title font lacks glyphs | The title font has no donor / is missing a `supplement` |
| Double-clicking the font does not open it in the Windows preview | A long-standing issue with the old base fonts; it does not affect the game; inspect it with `fontverify.py info` |
| The fonts are very large | Only the characters used by the current translation are stitched; adding characters triggers an automatic re-stitch |

---

## 11. Distribution Reminder

Stitched fonts are derivative works of "the game's original fonts + commercial/system
donors" and are for local use only — do not upload them, bundle them, or commit them
to the repository. See [Fonts & distribution](fonts-and-distribution.md).

---

See also: [New language fonts](new-language-fonts.md) ·
[Translations & packs](translation-and-packs.md) ·
[Build & install](build-and-install.md) · [Release](release.md) ·
[Fonts & distribution](fonts-and-distribution.md).
