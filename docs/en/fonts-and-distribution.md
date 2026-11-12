# Fonts and Distribution Restrictions

## Summary

**Stitched fonts are for local use only — do not distribute them.**

The release build does **not** stitch fonts by default: it simply replaces the game's four fonts with the complete Noto fonts, and those can be redistributed with the package
(see [`release.md`](release.md)). What follows describes the optional stitching path.

`build/fonts/<lang>/*.ttf` are derivative works generated with fontstitch:

- the base is the game's original Latin font (Ascaron / Port Royale 2);
- the donors are system or commercial fonts: Microsoft YaHei, STZhongsong,
  Source Han Serif, ZhongQi ZhiMang, Noto Serif JP, and others;
- **one `presets/<lang>.toml` per language**: that directory is not committed to the
  repository and is created by copying `presets.example.toml`; there are currently
  `zh` and `ja`, each independent of the other.

The licenses of these fonts themselves usually **do not permit redistribution after
modification**; uploading, packaging, shipping the stitched result in a release, or
committing it to the repository may all violate those licenses.

## Safeguards Already in Place

- `.gitignore` ignores `assets/fonts/original/` and `build/fonts/`;
- `subset_fonts.py` writes a `不要分发.txt` ("do not distribute") file into the output directory;
- the deployment script copies only the four `.ttf` files into `fonts/<lang>/` in the game directory and does not carry the notice file into the font directory;
- the repository commits only the stitching code and the presets, never any font files.

## What to Do If Someone Else Wants to Use It

Have them prepare the following on their own machine:

1. Export the original fonts from their own copy of the game:
   ```bash
   python src/tools/font/extract_fonts.py --game-dir "<game dir>" --out assets/fonts/original
   ```
2. For each language, prepare `src/tools/font/fontstitch/presets/<lang>.toml`
   (you can copy it from `presets.example.toml`), and install or otherwise provide your own donors;
3. Check the prerequisites and generate:

```bash
python src/tools/font/subset_fonts.py --check
python src/tools/font/subset_fonts.py --all
```

Each language is written to `build/fonts/<lang>/`; at deployment time it is copied into
`fonts/<lang>/` in the game directory, without overwriting the originals in the root directory.
For the full checklist, see [`new-language-fonts.md`](new-language-fonts.md).

## Related Files

- `src/tools/font/subset_fonts.py`: the stitching entry point;
- `src/tools/font/fontstitch/`: the stitching engine and the donor presets;
- [`build-and-install.md`](build-and-install.md): the font notes in the build process.
