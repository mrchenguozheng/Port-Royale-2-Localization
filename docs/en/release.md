# Release

## Supported game build

**Only GOG English `1.1.2.3` is supported.** GOG French, Steam English and other
builds are out of scope; do not deploy these packages to them. Future work is in
[Pending issues](pending.md).

## Version numbering

First public release: `v1.0.0`. Use `v0.9.0` while a clean GOG copy is still unverified.

| Version | Purpose |
|---|---|
| `v0.9.0` | RC |
| `v1.0.0` | First public release |
| `v1.0.x` | Fixes, docs, small font fixes |
| `v1.1.0` | New language packs or notable features |
| `v1.2.0` | New game builds (Steam / GOG French, etc.) |
| `v2.0.0` | Incompatible pack format or runtime contract |

The release version and `PR2_RUNTIME_VERSION` are separate.

Regenerate before tagging:

```bat
python src\tools\pack\make_release.py --lang zh --lang ja --version v1.0.0
git tag v1.0.0
git push origin v1.0.0
```

## Goals

Players download a language pack, extract it into the game directory, and it is ready to
use:

```
PR2-zh-v1.0.0.zip
├─ PR2Launcher.exe
├─ PR2LauncherGUI.exe      ← GUI: choose a language and launch
├─ PR2TextSource.dll
├─ ui/
│  ├─ zh.ini
│  ├─ en.ini
│  └─ ja.ini
├─ PR2Packs/
│  ├─ zh.txt
│  └─ locale.ini
├─ fonts/
│  └─ zh/
│     ├─ ARIAL.TTF
│     ├─ ELGRECO_.TTF
│     ├─ Tiepolo_black.ttf
│     └─ Tiepolo_bold.ttf
├─ README.txt
├─ NOTO-SOURCES.txt       ← font source notes (not placed in fonts/)
├─ RUNTIME-VERSION        ← runtime version, used for language pack compatibility checks
└─ OFL.txt
```

`fonts/<lang>/` holds only the four TTFs, no documentation files; the game scans this
directory. Font source notes all live in the pack root as `NOTO-SOURCES.txt`.

The launcher uses path redirection so the game reads the matching subdirectory, and
**does not overwrite the original fonts in the `fonts/` root**. A single game directory
can hold several language subdirectories; the launcher selects one via `locale.ini` or
`--lang`, while an original launch still uses the root directory.

Players can also double-click `PR2LauncherGUI.exe`: pick a language from the list →
"Launch selected language"; "Launch original" goes straight to English. The GUI merely
calls `PR2Launcher.exe --lang=…`.

A language pack carries its own display name and GUI language:

```toml
# src/packs/zh.toml
alias = "简体中文"
gui = "zh"
```

After compilation these are written at the top of the language pack:

```
# pack-meta alias=简体中文
# pack-meta gui=zh
```

The game ignores `#` comments; the GUI reads them and then:

- the list shows `alias`;
- when switching to that language pack, the interface text switches to the
  `ui/<gui>.ini` matching `gui`.

A pack without `# pack-meta` shows the language code directly in the list; external
alias overrides are no longer supported.

After a successful GUI launch, the GUI writes the selected language straight back:

```ini
# PR2Packs/locale.ini
language=zh
```

The next time it opens, it reads this value, and double-clicking `PR2.exe` directly uses
the same language too.

The display name comes only from the pack's `# pack-meta alias`; the interface language
comes from `# pack-meta gui`. Without `gui` metadata it follows the Windows UI language,
then falls back to English.

A language pack can declare a minimum runtime version:

```
# pack-meta min_runtime=1
```

When `min_runtime` is higher than the current runtime version, the GUI/launcher refuses
to launch and prompts for an update, so an "old DLL + new language pack" combination
cannot silently leave text untranslated.

The package does not include the game itself, `.cpr` files, maps, music, or any other game
assets.

## Fonts

The release **does not stitch** fonts; it replaces them directly with complete Noto
fonts:

| Game file | Font |
|---|---|
| `ARIAL.TTF` | Noto Sans SC/JP Regular |
| `ELGRECO_.TTF` | Noto Serif SC/JP Black |
| `Tiepolo_black.ttf` | Noto Serif SC/JP Black |
| `Tiepolo_bold.ttf` | Noto Serif SC/JP Bold |

- **No subsetting**: the full character set is kept;
- VF files are instantiated into static weights;
- The fonts use the SIL OFL 1.1, and the release ships `OFL.txt`;
- Where to obtain them:
  - Google Fonts: Noto Sans SC / Noto Serif SC / Noto Sans JP / Noto Serif JP
  - <https://fonts.google.com/noto>
  - <https://openfontlicense.org/>

The fonts are large (about 50 MB for one Chinese set, about 32 MB as a zip). That is the
price of "no subsetting".

The release keeps four separate TTFs and **does no deduplication via "aliasing/hard-linking
files with identical glyphs"**: different game filenames may later be given different fonts
or weights, and deduplication would lock away that flexibility.

If the machine already has static `NotoSansSC-Regular`, `NotoSerifSC-Bold`,
`NotoSerifSC-Black` and similar files, generation only copies and renames them and
**does not need fontTools**. Only when the source files are `*-VF.ttf` variable fonts is
fontTools needed to instantiate them into static weights.

### Font cache

Generated results are cached in:

```
build/font-cache/noto/
```

The cache key includes the SHA-256 of the source font content, the weight, the target
filename, the fontTools version and the cache version: a recalculation happens only when
the source font or the parameters change. Packing the same language a second time uses
the cache directly.

Force a recalculation:

```bat
python src\tools\font\make_noto_fonts.py --lang zh --out <directory> --no-cache
```

Use a different cache directory:

```bat
python src\tools\font\make_noto_fonts.py --lang zh --out <directory> --cache-dir D:\font-cache
```

`make_release.py` reuses the cache by default; to force a recalculation:

```bat
python src\tools\pack\make_release.py --lang zh --version v1.0.0 --no-font-cache
```

Stitched fonts (`subset_fonts.py`) have a separate `.stitch.json` cache, keyed by the
character set in use, the donor font and the version, so stitching is not repeated.

## When fonts are missing

### How the program detects it

On a localized launch it checks:

```
<game directory>\fonts\<lang>\
├─ ARIAL.TTF
├─ ELGRECO_.TTF
├─ Tiepolo_black.ttf
└─ Tiepolo_bold.ttf
```

If any one of the four files is missing, the font set counts as "incomplete".

### How the program handles it

**GUI (`PR2LauncherGUI.exe`)**

It shows a dialog:

> `fonts\zh\ has no TTF fonts. Starting anyway will use the original Latin fonts; Chinese text may be missing. Start anyway?`

- Choose "Yes": continue launching;
- Choose "No": cancel.

**Launcher (`PR2Launcher.exe`)**

Even if the GUI is bypassed, it checks again:

- Fonts complete: sets `PR2_FONT_DIR=<lang>` and redirects to `fonts\<lang>\`;
- Fonts incomplete: sets no redirection, falls back to the original fonts in the `fonts\`
  root, and prints to the console:

```
[PR2Launch] fonts\zh\ 字体不完整，回退到原版根目录字体
```

*(The message reads: "fonts\zh\ font set incomplete, falling back to the original root
fonts".)*

The game can then start, but Chinese text will most likely render blank; only the original
Latin characters display correctly.

### What the user should do

1. **Check the directory**
   Confirm that the game directory really contains:

   ```
   fonts\zh\ARIAL.TTF
   fonts\zh\ELGRECO_.TTF
   fonts\zh\Tiepolo_black.ttf
   fonts\zh\Tiepolo_bold.ttf
   ```

2. **Extract the fonts again**
   Extract the whole `fonts\<lang>\` directory from the release zip; copying only the
   language pack `PR2Packs\<lang>.txt` is not enough.

3. **Do not put them in the root directory**
   Keep the original fonts in the `fonts\` root; localized fonts must go in the
   `fonts\<lang>\` subdirectory.

4. **Check antivirus software**
   Font files are large and are occasionally quarantined; restore them and start again.

5. **Make sure the language codes match**
   The language code in `PR2Packs\<lang>.txt`, `fonts\<lang>\` and `language=` in
   `locale.ini` must be the same code (for example, all `zh`).

6. **Still want to launch**
   You can choose to continue, but you will only see the original Latin fonts; missing
   Chinese text does not mean the game is broken.

### Original fonts

The four original TTFs stay in the `fonts\` root and are never overwritten by
localization. Before the launcher replaces them for the first time, it also backs them up
to `fonts\_original\` (SHA-256 verified); `PR2Launcher.exe --vanilla` uses the original
fonts from the root directory.

## Packaging

### 1. Build the runtime

Requires Visual Studio with the C++ desktop workload:

```bat
cd C:\path\to\pr2-localization
src\build_injector.bat
```

Outputs:

```
build\PR2Launcher.exe
build\PR2LauncherGUI.exe
build\PR2TextSource.dll
build\ui\zh.ini / en.ini / ja.ini
```

Skip this step when only translations changed.

### 2. Package language packs and fonts

```bat
python src\tools\pack\make_release.py --lang zh --lang ja --version v1.0.0
```

One language at a time is also fine:

```bat
python src\tools\pack\make_release.py --lang zh --version v1.0.0
```

Output:

```
dist\PR2-zh-v1.0.0.zip
dist\PR2-ja-v1.0.0.zip
```

`make_release.py` automatically:

- compiles the language packs;
- builds Noto fonts (default `--fonts noto`);
- copies the runtime, `ui/`, `PR2Packs/` and fonts;
- writes `RUNTIME-VERSION` and the supported-build note;
- packs `README.txt`, `OFL.txt`, `NOTO-SOURCES.txt`.

First-time VF instancing needs:

```bat
python -m pip install fonttools
```

Font results are cached in `build\font-cache\noto\` and reused. Force a rebuild:

```bat
python src\tools\pack\make_release.py --lang zh --version v1.0.0 --no-font-cache
```

### 3. Packaging model

Releases currently ship one bundle per language (runtime + pack + fonts) so players
can extract and play.

A separate Runtime + Language split is kept as a future option; it is not enabled
yet. Revisit it when the number of languages grows or the runtime needs frequent
independent updates.

### 4. Verify before publishing

1. Extract into a clean game copy;
2. Run `PR2LauncherGUI.exe`;
3. Select a language and launch;
4. Check UI text, fonts and the original launch;
5. Confirm `README.txt` says the supported build is **GOG English 1.1.2.3**.

To generate only the Noto fonts without running stitching:

```bash
python src/tools/font/make_noto_fonts.py --lang zh --out dist/PR2-zh-v1.0.0/fonts
```

### Other languages

Add a mapping to `LANGS` in `src/tools/font/make_noto_fonts.py`, for example:

```python
"ko": {
    "sans": ("NotoSansKR", 400),
    "serif": ("NotoSerifKR", (700, 900)),
    "label": "Korean",
},
```

Font naming must match the local installation; if the corresponding Noto fonts are not
available, download and install them from Google Fonts first.

## Advanced: subsetting and stitching

Neither is part of the default release flow:

- **Subsetting**: `fontsubset.py` shrinks a font according to the characters used;
- **Stitching**: `subset_fonts.py` stitches the original Latin fonts together with a donor,
  preserving the original glyphs.

Stitched fonts are derivative works: **for personal use only, never put them in a public
release**. `make_release.py --fonts stitch` is only for private packages.

## GitHub Actions

Triggered by tags, one package per language:

```yaml
on:
  push:
    tags: ['v*']

jobs:
  release:
    runs-on: windows-latest
    strategy:
      matrix:
        lang: [zh, ja]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install fonttools
      - run: python src/tools/pack/make_release.py --lang ${{ matrix.lang }} --version ${{ github.ref_name }}
      - uses: softprops/action-gh-release@v2
        with:
          files: dist/*.zip
```

Prerequisites: the injector has been built and placed in `build/`; the Noto fonts are
available on the runner (or have been downloaded to a fixed path beforehand).
