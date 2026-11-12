# Adding a New Language and Stitching Fonts: What You Need to Prepare

This repository **contains no font binaries**. If you clone it and want to build your own language pack and stitch fonts, you have to prepare the following items yourself.

## 1. The game's original Latin fonts (required)

`assets/fonts/original/` is listed in `.gitignore`, so it is empty after cloning. Export the fonts from your own copy of the game:

```bash
python src/tools/font/extract_fonts.py --game-dir "<game directory>" --out assets/fonts/original
```

This produces:

```
ARIAL.TTF  ELGRECO_.TTF  Tiepolo_black.ttf  Tiepolo_bold.ttf
```

You can also set `PR2_ORIG_FONTS`, or use `subset_fonts.py --src`, to point at an original-font directory located elsewhere.

## 2. Donor fonts (required, and not in the repository)

One configuration per language:

```
src/tools/font/fontstitch/presets/<language>.toml
```

The structure is uniform, and there is no longer an outer section such as `[zh]`:

```toml
# presets/zh.toml
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

- `[[pair]]`: one primary donor for each game font;
- `[[supplement]]`: fills in characters that the primary donor does not cover;
- `[fallback]`: the final fallback.

The entire `presets/` directory is kept out of the repository (the paths may contain machine-specific information); only `presets.example.toml` is committed. When you add a new language, the template language's configuration is copied automatically to `presets/<language>.toml`, and you then change the donors for that language.

## 3. fontTools (required)

```bash
python -m pip install fonttools
```

Alternatively, set `PR2_FONTTOOLS_SITE` to point at a site-packages directory where fontTools is already installed.

## 4. Font constraints

- The donor must have TrueType `glyf` outlines;
- the donor's UPM must match that of the corresponding game font: Arial 2048, ElGreco/Tiepolo 1000;
- characters not covered by the primary donor are filled in with `[[supplement]]`;
- each language is generated separately into `build/fonts/<language>/`, without affecting the others.

## 5. Generating and deploying

```bash
# Check the original fonts, the donors, and fontTools
python src/tools/font/subset_fonts.py --check

# Stitch a single language
python src/tools/font/subset_fonts.py --lang zh --force

# Stitch every configured language
python src/tools/font/subset_fonts.py --all --force
```

Output:

```
build/fonts/zh/ARIAL.TTF ...
build/fonts/ja/ARIAL.TTF ...
```

When deploying, copy only the font set for the **target language** into the game's `fonts\` directory.

## 6. Distribution restrictions

Stitched fonts are derivative works of "the game's original fonts + commercial donors" and are **for local use only**. Do not upload them, package them, or commit them to the repository. See [`fonts-and-distribution.md`](fonts-and-distribution.md) for details.

Related documents: [new-language.md](new-language.md), [release.md](release.md), [build-and-install.md](build-and-install.md).
