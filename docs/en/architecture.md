# Architecture and Refactoring Plan

> This document records the current layering, the known risks, and the refactoring order for making only the necessary changes.
> Principles: no central language list, no microservices, no plugin system.

## Current layering

```
PR2LauncherGUI.exe   select language, show alias, check fonts, write back locale.ini, end a hung PR2.exe from this folder
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
src/editor/server.py editor HTTP service; per-domain modules under api/
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
| Font name/integrity checks scattered | `pr2_common` unifies the launcher and GUI | The Python build writes by output filename and does not share the same constants |
| locale semantics diverge | `pr2_common` unifies reads; the GUI is the only writer | Running `PR2.exe` directly bypasses the launcher |
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

- Add font helpers in `src/injector-rs/pr2_common/src/lib.rs`:
  - the four font names;
  - the `fonts/<lang>/` integrity check.
- The launcher and GUI were switched to call the same implementation;
- The launcher's original font backup also reuses the font names;
- Build and verify both the missing-font and complete-font paths.

Status: done. `pr2_common` unifies font names and the integrity check; the Rust build and the missing-font fallback compile, but the real game font chain is not yet exercised.

### Step 2: Unified locale

- Extract a minimal locale read/write-back function;
- Make it explicit: only the GUI writes after a successful launch; the CLI only reads;
- The GUI no longer keeps a second copy of the language state.

Status: done. `pr2_common` unifies reading and writing back; the GUI is still the only writer; both launching the CLI directly and writing back after a GUI launch were verified.

### Step 3: Unified build artifact entry points

- Make `make_release`, `apply_patch`, and `pr2ctl` share the same
  "build language pack + fonts + runtime" function;
- Do not rewrite the existing tools; only consolidate the duplicated orchestration.

Status: done. `pack/build_artifacts.py` unifies language pack compilation and font generation:
- Release: `noto`, output to `stage/fonts/<lang>/`;
- Local: `stitch`, output to `build/runtime/fonts/<lang>/`.
Runtime file copying is still handled by `make_release` / `pr2ctl` according to their own targets, and is not forcibly merged.

### Step 4: Runtime version check

- Write the runtime version into release packages;
- The DLL/launcher report a clear error when the minimum version required by the language pack does not match;
- No automatic updates.

Status: done. Language packs write `min_runtime`, and the GUI/launcher refuse to start when the version is too low;
release packages write `RUNTIME-VERSION`. Integer versions only, no automatic updates.

### Step 5: Editor service split by domain

The old `src/editor/server.py` was one 1424-line file holding data access, validation,
context inference, language management, build/font/start jobs, and HTTP dispatch.
After the split:

| File | Lines | Responsibility |
|---|---|---|
| `src/editor/server.py` | 509 | constants, `health_info`/`server_instances`, 4 meta routes, `Handler`, startup and CLI |
| `src/editor/api/store.py` | 116 | entry read/write and mtime-based caches |
| `src/editor/api/request.py` | 25 | `Req`: query/body of one request plus the two send exits |
| `src/editor/api/translate.py` | 540 | translation domain: validation, context, rule trace, placeholders, filters, single-row write/patch (14 routes) |
| `src/editor/api/langs.py` | 334 | language domain: list/progress/new language, placeholder meanings, term exceptions (7 routes) |
| `src/editor/api/install.py` | 366 | install domain: game dirs, build/deploy/start jobs, fonts (16 routes) |

- Routing becomes table-driven: each module exports `ROUTES = {(method, path): func}`
  and the server merges them into `ROUTER`; `get_api`/`post_api` only look up the
  table and call the function with a `Req`, so branch logic leaves the Handler;
- Changing the data root has one path only: `set_data_root` calls `T.set_src`
  (translations/source), `ST._ALL_CACHE`, `LG.set_root` (both glossary files and
  caches), and `IN.set_presets_dir` (font presets); the server keeps no second path table;
- The contract is unchanged: paths, query parameters, request bodies, returned JSON,
  status codes, and access logs all stay as they were;
- Known dead route: the `GET /api/rule-hits` branch called `rule_hits()`, which never
  existed in the repository (it could only return 500, and the frontend `app.ts`
  never called it), so it was removed with the split; route count 47→46;
- Same kind of cleanup: the frontend "context inference" dialog (`openCtx`) was never
  wired up; inline context only uses `/api/context-batch`. The dialog and
  `GET /api/context` were removed together, route count 46→45;
- Another pass against actual frontend calls: the frontend only uses the single-entry
  `POST /api/placeholder-meaning` plus `/api/entry-info`, so the plural
  `GET`/`POST /api/placeholder-meanings` had no caller; and `POST /api/font/stitch`
  duplicates the CLI path (`subset_fonts.py`), while the install page only uses
  `font-status` / `font/export`. All three were removed, route count 45→42;
- With a single product, `POST /api/save` has no user either: the frontend only uses
  `/api/patch` (multi-row, existing file order, per-row placeholder checks), and
  `save_all`'s whole-table order check only matters to a caller that holds all 3548
  entries. The route and `save_all` were removed together, route count 42→41;
- After the standalone translator package was removed, `server.py`'s
  `TRANSLATOR`/`TRANSLATOR_LANG` constants, its three `if TRANSLATOR` branches,
  `--translator`/`--translator-lang` and the matching `global` assignment had no
  consumer left and were deleted (server 539→509);
- The cleanup also restored `_ATTN_CACHE = {}` in `api/translate.py`: an earlier
  server-constant cleanup dropped its definition, so `filter=attention` would 500;
  the unused `PH_MEAN` table was removed at the same time;
- The 41-route contract for agents is a separate document:
  [Editor API contract](agent-api.md);
- The stage-1 `--data` / `--presets-dir` flags remain, and tests run POST against a
  temporary data root.

Status: done. `tests/test_server_api.py` 5 tests (21 GET routes all 200, POST writes
to the temporary root, real repository file SHAs unchanged); `check.py` 46 tests;
`engine_text --check` reports "一致" for both zh and ja; pack SHAs match the
pre-refactoring baseline (zh `2B209420…920F`, ja `17517FB6…FAB`).

## Native programs migrated to Rust

The three C++ native programs are now a Rust workspace at `src\injector-rs\`:

| Crate | Output | Old implementation |
|---|---|---|
| `pr2_common` | none (library) | shared parts of `pr2_fonts.h` / `pr2_locale.h` / `pr2_version.h` |
| `pr2_text_source` | `PR2TextSource.dll` | `pr2_text_source.cpp` + `pr2_text_pack.c` |
| `pr2_launcher` | `PR2Launcher.exe` | `pr2_launcher.cpp` |
| `pr2_launcher_gui` | `PR2LauncherGUI.exe` | `pr2_launcher_gui.cpp` |

- The workspace `.cargo\config.toml` pins `i686-pc-windows-msvc`, matching the 32-bit game process;
- `build_injector.bat` now runs `cargo build --release --locked` and copies the artifacts
  and `ui\*.ini` into `build\runtime\`;
- The GUI is compiled with `#![windows_subsystem = "windows"]`, so double-clicking it does
  not open a console;
- The DLL replaces SEH with `VirtualQuery` readability checks; the vtable scan, thunk patch,
  whole-table replacement, `PR2Packs` / `overrides` loading and log limits preserve the old
  behavior;
- The old C++ sources and `src\injector\ui` were moved out of the working tree; the UI files
  now live in `src\injector-rs\ui\`.

Verification:

- `cargo build --release` passes; all three outputs are 32-bit;
- a 32-bit `LoadLibraryA` loads and frees the Rust DLL;
- a fake 32-bit `PR2.exe` plus `PR2Launcher.exe --lang=zh` injects successfully; the DLL log
  reports `pack 'zh' ...: 3548 overrides`;
- `build\runtime\PR2LauncherGUI.exe` launches and shows the pack count in Chinese;
- the GUI uses a single-column layout at a `560x400` base size, scales with system DPI,
  and shows title/subtitle, language pack row, launch/vanilla/refresh row, a separate
  end-process button, status box and footer hint; all controls fit inside the client
  area in the Chinese and Japanese UI.
- `python src\tools\check.py` passes 55 tests and `tests.test_quick` passes 9.

Known issue (recorded, not fixed): after finishing the first tutorial campaign and
clicking exit, `PR2.exe` may stay alive with a black or white residual window, sometimes
with an MSVC Runtime Error dialog. It has reproduced with the original English build,
the GUI-launched original build, and the Chinese build; a single successful original
exit is not enough to rule it out. No crash dump for that path is available yet. The
GUI's end-process action is only a fallback.

Not yet verified: the three hooks inside the real game (`A2dLib-2.20A.dll` IAT / vtable /
ResolveByHash). The fake host does not load A2dLib, so `A2dLib not loaded` and
`Add not found` in the log are expected.

## Verification gate

At a minimum, every step must satisfy:

1. `src\build_injector.bat` succeeds;
2. `python src\tools\check.py` passes;
3. launching the GUI shows the language list;
4. running `PR2Launcher.exe` directly starts the game according to `locale.ini`;
5. when fonts are missing, it falls back to the original fonts in the root directory without crashing.
