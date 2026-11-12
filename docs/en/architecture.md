# Architecture and Refactoring Plan

> This document records the current layering, the known risks, and the refactoring order for making only the necessary changes.
> Principles: no central language list, no microservices, no plugin system.

## Current layering

```
PR2LauncherGUI.exe   select language, show alias, check fonts, write back locale.ini
        │
        ▼
PR2Launcher.exe      back up fonts, resolve font directory, inject DLL, launch PR2.exe
        │
        ▼
PR2TextSource.dll    hook the game's text lookups + redirect font paths + read the language pack
```

Build side:

```
compile_pack.py      translations → PR2Packs/<lang>.txt (with # pack-meta)
make_noto_fonts.py   Noto fonts → fonts/<lang>/*.TTF (with caching)
make_release.py      assemble the release package
apply_patch.py       local build + deploy
pr2ctl               editor install/deploy backend
```

## File contracts

| Path | Contract |
|---|---|
| `PR2Packs/<lang>.txt` | `hash = text`; may start with `# pack-meta alias=…` / `gui=…`; the game ignores `#` |
| `PR2Packs/locale.ini` | `language=<code>`; the game's default language and the GUI's only language state |
| `fonts/<lang>/` | Four TTFs with fixed filenames; fonts only, no readme files |
| `ui/<lang>.ini` | GUI interface translations; selected by the pack's `gui` metadata |
| `PR2_PACK_LANG` | Language override for this process; set by `--lang`, never written to a file |
| `PR2_FONT_DIR` | Font subdirectory for this process; set when the fonts are complete |

## Pre-refactoring risks and their handling

| Risk before refactoring | Handling | Remaining boundary |
|---|---|---|
| Font name/integrity checks scattered | `pr2_fonts.h` unifies the launcher and GUI | The Python build writes by output filename and does not share the C header |
| locale semantics diverge | `pr2_locale.h` unifies reads; the GUI is the only writer | Running `PR2.exe` directly bypasses the launcher |
| Many build entry points | `build_artifacts.py` unifies language packs and fonts | Runtime file copying is still handled separately by release/deploy |
| Implicit file formats | `min_runtime` adds an integer version check | Still a minimal format, with no schema or validator |
| Multiple language packs overwrite the runtime | `min_runtime` + `RUNTIME-VERSION` | Direct `PR2.exe` bypasses the check; no automatic updates |

## Refactoring principles

- Eliminate "the same rule written twice" first; do not abstract first;
- Prefer a small header or small module for shared code; do not build a framework;
- Keep a single source of language state: `locale.ini`;
- Language packs stay self-describing; no central list;
- Every step must be buildable, testable, and revertible on its own.

## Step-by-step plan

### Step 1: Shared font contract

- Add `src/injector/pr2_fonts.h`:
  - the four font names;
  - the `fonts/<lang>/` integrity check.
- The launcher and GUI were switched to call the same implementation;
- The launcher's original font backup also reuses the font names;
- Build and verify both the missing-font and complete-font paths.

Status: done. `pr2_fonts.h` unifies font names and the integrity check; the build and the missing-font fallback were verified.

### Step 2: Unified locale

- Extract a minimal locale read/write-back function;
- Make it explicit: only the GUI writes after a successful launch; the CLI only reads;
- The GUI no longer keeps a second copy of the language state.

Status: done. `pr2_locale.h` unifies reading and writing back; the GUI is still the only writer; both launching the CLI directly and writing back after a GUI launch were verified.

### Step 3: Unified build artifact entry points

- Make `make_release`, `apply_patch`, and `pr2ctl` share the same
  "build language pack + fonts + runtime" function;
- Do not rewrite the existing tools; only consolidate the duplicated orchestration.

Status: done. `pack/build_artifacts.py` unifies language pack compilation and font generation:
- Release: `noto`, output to `stage/fonts/<lang>/`;
- Local: `stitch`, output to `build/fonts/<lang>/`.
Runtime file copying is still handled by `make_release` / `pr2ctl` according to their own targets, and is not forcibly merged.

### Step 4: Runtime version check

- Write the runtime version into release packages;
- The DLL/launcher report a clear error when the minimum version required by the language pack does not match;
- No automatic updates.

Status: done. Language packs write `min_runtime`, and the GUI/launcher refuse to start when the version is too low;
release packages write `RUNTIME-VERSION`. Integer versions only, no automatic updates.

## Verification gate

At a minimum, every step must satisfy:

1. `src\build_injector.bat` succeeds;
2. `python src\tools\check.py` passes;
3. launching the GUI shows the language list;
4. running `PR2Launcher.exe` directly starts the game according to `locale.ini`;
5. when fonts are missing, it falls back to the original fonts in the root directory without crashing.
