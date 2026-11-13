# Architecture and File Contracts

> This page records the current layering, file contracts, current boundaries and known
> issues only. Completed refactor phases, old route changes and the C++ migration
> comparison are in [Refactoring History](refactor-history.md).
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

## Native programs and build layout

The three native programs live in the Rust workspace at `src\injector-rs\`:

| Crate | Output | Responsibility |
|---|---|---|
| `pr2_common` | none (library) | shared font names/integrity, locale and runtime version logic |
| `pr2_text_source` | `PR2TextSource.dll` | text hook, font path redirection, pack and overrides loading |
| `pr2_launcher` | `PR2Launcher.exe` | font backup, font directory resolution, DLL injection, game launch |
| `pr2_launcher_gui` | `PR2LauncherGUI.exe` | language selection, status display, launch and end-process actions |

- The workspace `.cargo\config.toml` pins `i686-pc-windows-msvc`, matching the 32-bit game process;
- `build_injector.bat` runs `cargo build --release --locked` and copies the artifacts and
  `ui\*.ini` into `build\runtime\`;
- The GUI is compiled with `#![windows_subsystem = "windows"]`, so double-clicking it does
  not open a console;
- The old C++ implementation is no longer in the working tree. This page does not keep
  file-level comparisons; see the archived history when needed.

## File contracts

| Path | Contract |
|---|---|
| `PR2Packs/<lang>.txt` | `hash = text`; may start with `# pack-meta alias=…` / `gui=…`; the game ignores `#` |
| `PR2Packs/locale.ini` | `language=<code>`; the game's default language and the GUI's only language state |
| `fonts/<lang>/` | Four TTFs with fixed filenames; fonts only, no readme files |
| `ui/<lang>.ini` | GUI interface translations; selected by the pack's `gui` metadata |
| `PR2_PACK_LANG` | Language override for this process; set by `--lang`, never written to a file |
| `PR2_FONT_DIR` | Font subdirectory for this process; set when the fonts are complete |

## Current boundaries

| Risk | Handling | Remaining boundary |
|---|---|---|
| Font name/integrity checks scattered | `pr2_common` unifies the launcher and GUI | The Python build writes by output filename and does not share the same constants |
| locale semantics diverge | `pr2_common` unifies reads; the GUI is the only writer | Running `PR2.exe` directly bypasses the launcher |
| Many build entry points | `build_artifacts.py` unifies language packs and fonts | Runtime file copying is still handled separately by release/deploy |
| Implicit file formats | `min_runtime` adds an integer version check | Still a minimal format, with no schema or validator |
| Multiple language packs overwrite the runtime | `min_runtime` + `RUNTIME-VERSION` | Direct `PR2.exe` bypasses the check; no automatic updates |

## Design principles

- Eliminate duplicated rules first; do not abstract first;
- Prefer a small module for shared code; do not build a framework;
- Keep a single source of language state: `locale.ini`;
- Language packs stay self-describing; no central list;
- Every step must be buildable, testable, and revertible on its own.

## Launcher UI

The GUI uses a single-column layout at a `560x400` base size (96 DPI):

| Region | Base rectangle | Notes |
|---|---|---|
| Title | `24,16,496,34` | Segoe UI 16pt bold, dark blue |
| Subtitle | `24,54,496,20` | 9pt grey, key `subtitle` |
| Separator | `24,82,496,2` | `SS_ETCHEDHORZ` |
| Language label | `24,94,496,20` | 10pt |
| Language combo box | `24,116,496,30` | Actual height follows the system combo-box font |
| Main action row | `24,158` | "Launch selected language" `220x42`, default; "Launch original" `160x42`; "Refresh" `90x42` |
| End-process button | `304,214,216,34` | Right-aligned, confirmation dialog kept |
| Status box | `24,262,496,52` | `WS_EX_CLIENTEDGE`, white background |
| Footer hint | `24,322,496,36` | Key `hint.footer`, up to two lines |

- At startup it calls `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)` and scales
  rectangles and font sizes from the system DPI;
- Fonts are created with `CreateFontW` in Segoe UI: title 16pt bold, normal controls 10pt,
  status/footer 9pt; the three font handles are released with `DeleteObject`;
- `WM_CTLCOLORSTATIC` sets title, subtitle, footer and status colors;
- `ui/zh.ini`, `ui/en.ini` and `ui/ja.ini` carry `subtitle` and `hint.footer`; missing keys
  fall back to `BUILTIN` in `strings.rs`.

Verified in the game directory: the window is `560x400`, all child controls fit inside
the client area without overlap; Chinese and Japanese UI switching works, and the longest
footer text fits.

## Known issue: black/white screen on exit

Status: **not fixed**, recorded only. The GUI's "End game process" action is only a
fallback, not a fix.

- After finishing the first tutorial campaign, clicking exit may leave `PR2.exe` alive
  with a black or white residual window;
- An MSVC Runtime Error dialog sometimes appears, with Program pointing at `PR2.exe`;
- It has reproduced with the original English build, the GUI-launched original build,
  and the Chinese build; a single successful original exit is not enough to rule it out;
- No crash dump for that path is available yet, and the root cause is not located.

## Verification gate

At a minimum, every step must satisfy:

1. `src\build_injector.bat` succeeds;
2. `python src\tools\check.py` passes;
3. launching the GUI shows the language list;
4. running `PR2Launcher.exe` directly starts the game according to `locale.ini`;
5. when fonts are missing, it falls back to the original fonts in the root directory without crashing.

## Related documents

- [Editor API contract](agent-api.md)
- [Refactoring History](refactor-history.md)
