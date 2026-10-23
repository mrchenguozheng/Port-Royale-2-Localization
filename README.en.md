# Port Royale 2 Localization

A localization project for **Port Royale 2**: UI text is replaced through an
external language pack, and the original `PR2.exe` is never modified.

[中文说明](README.md) · [Documentation index](docs/README.md)

---

## Read this first: support and test status

**Only the GOG English build has been patched and tested in-game.** Other builds:

| Build | Patched? | Result |
|---|---|---|
| **GOG English** `1.1.2.3` | ✅ Yes | ✅ **Tested** — UI text, language switching and CJK fonts work |
| **GOG French** `1.1.2.42` | ❌ No | ⚠️ **Untested** (string table extracted only as a reference) |
| **Steam English** | ✅ Injection tried | ❌ **Tested, did not take effect** — see below |

### Why Steam does not work

The Steam `PR2.exe` is protected by Valve CEG. Changing even one byte makes it
fail at startup with `Application load error 3:0000065432`. This project therefore
uses runtime injection: the launcher injects a DLL into the game process, and the
DLL takes over the engine's text lookups without touching the exe.

In theory CEG should not interfere, but in practice the language pack did not take
effect in the Steam build. Open questions:

- whether CEG self-checks before the injection point;
- whether `A2dLib-2.20A.dll` lives elsewhere in the Steam build;
- whether the fixed hook offsets (taken from the GOG build) match the Steam build.

**Verify on the GOG English build before trying Steam.**
The investigation plan is in [Pending issues](docs/en/pending.md).

---

## Quick start

Requirements: Visual Studio (Desktop development with C++) and Python 3.11+
(currently 3.15).

```bat
start.bat
```

It starts the local workbench and opens the **Install & Launch** page in your
browser. It does **not** build anything automatically.

The page has a five-step wizard:

1. Select the game directory;
2. Prepare fonts;
3. Translate content;
4. Build language pack + fonts;
5. Deploy and launch.

You can also use the cards directly:

- **Build & Deploy**: build the injector, build language packs, deploy to the game directory;
- **Launch**: **Set as game language** writes `locale.ini`; **Launch (injected)** starts with the selected language;
- **Translation editor**: same workbench, switch tabs at the top.

During development, `apply_patch.bat` runs the whole chain: normalize → validate →
build → deploy → verify.

Launch with `PR2Launcher.exe` from the game directory
(**do not run `PR2.exe` directly**, it will not load a language pack).
To persist a language choice use **Set as game language**; launching once does not
write to disk. Release players use `PR2LauncherGUI.exe`, which writes the choice
back after a successful launch.

See [Build & Install](docs/en/build-and-install.md) for button details.

---

## Repository layout

```
pr2-localization/
├─ start.bat                  daily entry point: start the workbench
├─ apply_patch.bat            normalize → validate → build → deploy
├─ src/
│  ├─ live/                   translation source (saved by the editor)
│  ├─ seed/                   initial text (unlocked entry by entry)
│  ├─ orig/                   original English/French (read-only reference)
│  ├─ editor/                 translation editor (Astro frontend + server.py)
│  ├─ injector/               injector sources (C++)
│  └─ tools/
│     ├─ pack/                build, deploy, new language
│     ├─ text/                normalization, CJK rules, tokenization
│     ├─ font/                font stitching and export (fontstitch/)
│     ├─ analysis/            speaker, tone, width analysis
│     ├─ install/             pr2ctl build/deploy/launch implementation
│     └─ data/                names, places, tokenizer dictionaries
├─ assets/fonts/original/     original Latin fonts (gitignored; export yourself)
├─ build/                     artifacts: PR2Packs/, fonts/, injector
├─ docs/                      documentation
├─ glossary/                  terminology
└─ tests/                     rules and API tests
```

`start.bat` lives at the repository root because it targets people who received
the repository, not only people editing source.

| File | Role |
|---|---|
| `PR2Launcher.exe` | Launcher. Starts `PR2.exe` suspended, injects the DLL, resumes it (build artifact) |
| `PR2TextSource.dll` | Core logic. Hooks three engine text paths and replaces strings (build artifact) |
| `PR2Packs\` | Language packs. `<lang>.txt` + `locale.ini`; plain text is editable |
| `fonts\` | Localized fonts; missing CJK glyphs show as blanks |

---

## Adding a language

No C++ changes are required:

1. Run `start.bat`, open **Translation editor**, click **＋** next to the language
   dropdown and use an existing language as a template;
2. Translate and save (written to `src/live/<code>.toml`);
3. A `presets/<code>.toml` is created automatically from the template language;
   check or replace donors for the new language;
4. Build fonts and the language pack, then deploy.

Full steps with acceptance points: [New language](docs/en/new-language.md).
Font prerequisites: [New language fonts](docs/en/new-language-fonts.md).

Entries do not have to be complete — missing entries fall back to English.

---

## Documentation

| Document | Contents |
|---|---|
| [Documentation index](docs/README.md) | Use/build/translate/pending sections; start here |
| [Build & Install](docs/en/build-and-install.md) | Install page, build/deploy/launch, scripts |
| [New language](docs/en/new-language.md) | From font export to an in-game language |
| [Release](docs/en/release.md) | Per-language zips, Noto fonts, GitHub Actions |
| [New language fonts](docs/en/new-language-fonts.md) | Font/tool prerequisites for a new language |
| [Fonts & distribution](docs/en/fonts-and-distribution.md) | Stitching, donor licenses, redistribution limits |
| [Injector](docs/en/injection.md) | Runtime, three hook paths, source layout, build |
| [Architecture](docs/en/architecture.md) | Layers, file contracts, refactor record, boundaries |
| [Translations & packs](docs/en/translation-and-packs.md) | TOML format, validation, adding a language |
| [Glossary](glossary/README.md) | English/Chinese names for goods, ships, ranks, towns |
| [Pending](docs/en/pending.md) | Steam issues, untested French build, hook offsets |
| [Speaker tiers](docs/en/speaker-tiers.md) | Which lines identify a speaker, which are guesses (with CSV) |
| [Translation limits](docs/en/translation-limits.md) | What cannot be fixed, verified coverage, hook trade-offs |
| [Tone proposals](docs/en/tone-proposal.md) | 41 confident speakers + 668 entries for review |

---

## Known limitations

- **Hook targets are tied to game builds.** The code calls `A2dLib-2.20A.dll`
  functions at fixed offsets; another build (including GOG French `1.1.2.42`)
  will likely need new offsets, otherwise nothing takes effect.
- **A whole Chinese entry disappearing is a tokenization issue, not a tag issue.**
  The engine splits text on spaces; an unbroken CJK string that is too wide is
  dropped as a whole. Verify entry by entry in-game.
- **Fonts are per language.** Development uses stitched fonts in
  `build\fonts\<lang>\`; releases use full Noto. Deployment copies to
  `fonts\<lang>\` in the game directory and never overwrites the originals.
  New rare characters trigger a re-stitch; missing glyphs render as blanks.

---

## License

See [LICENSE](LICENSE).

## Language status

| Language | Entries | Status |
|---|---|---|
| Chinese `zh` | 3548 | ✅ Complete (layout and placeholder checks included) |
| Japanese `ja` | 3548 | ✅ Complete (3370 translations + 178 keep-original) |
| English/French | 3548 | Reference originals (`src/orig/`), no packs generated |

Japanese "keep original" means 178 entries that should not be translated:
symbols/numbers, engine IDs (`IDM_CONTEST_…`), key names (`ESC`/`CTRL`/`F10`),
copyright notices and developer names. The list is in
`src/live/keep_original.toml`; the compiler forces the English original back.

## Path conventions

Documentation and scripts do not contain machine-specific absolute paths: the game
directory is written as `<game directory>`, user directories use variables such as
`%USERPROFILE%`. `subset_fonts.py` reads original fonts from
`assets/fonts/original/` by default (gitignored), not from a particular machine.
