# Injector components

The runtime part of localizing *Port Royale 2*: **a launcher + a DLL + a language pack directory**.

**`PR2.exe` is never modified.** The launcher injects the DLL into the game process, and at runtime
the DLL takes over the engine's string lookups, feeding in the translations from `PR2Packs\`.
The original exe stays read-only throughout.

The source lives in `src\injector-rs\` (a Rust workspace); the build script is in `src\`.

---

## The three components

| File | Role |
|---|---|
| `PR2Launcher.exe` | Launcher. Starts `PR2.exe` suspended, injects the DLL, then resumes execution |
| `PR2LauncherGUI.exe` | GUI. Lists `PR2Packs\*.txt`; after you pick a language it calls the launcher above |
| `ui/<language>.ini` | GUI interface translations (UTF-8 key=value); selected by the pack's `# pack-meta gui` |
| Start of `PR2Packs\<language>.txt` | `# pack-meta alias=…` / `gui=…` / `min_runtime=…`; read by the GUI/launcher, the game ignores comments |
| `PR2TextSource.dll` | Main logic. Hooks the engine's three string-lookup paths and substitutes the translations |
| `PR2Packs\` | Language pack directory. Holds packs and configuration; the text can be edited directly, no rebuild required |

The GUI uses a single-column layout (`560x400` base at 96 DPI), scales with the system
DPI, and keeps the language picker, launch actions, the separate end-process action
and the status box in distinct rows. The footer hint is localized through the
`subtitle` and `hint.footer` keys in `ui/*.ini`.

---

## How it works

```
User double-clicks PR2Launcher.exe   (or the GUI calls it with --lang=xx)
   │  CreateProcessA("PR2.exe", CREATE_SUSPENDED)
   │  VirtualAllocEx + WriteProcessMemory + CreateRemoteThread(LoadLibraryA)
   ▼
PR2.exe loads PR2TextSource.dll, DllMain → InstallHook()
   │
   ├─ LoadEditFile()      determines the language (see below), loads PR2Packs\<language>.txt
   │                      then the optional PR2Packs\overrides\<language>.txt
   │
   ├─ hook #1  IAT: CStringManager::Add
   │            when the engine registers the main string table (MISSION_NPC_GOODS_INFO),
   │            replace_table() rebuilds the whole English table as a translated table
   │
   ├─ hook #2  vtable: CW32StringManager::AddStringRes / LoadStringRes
   │
   └─ hook #3  A2dLib CScreenStrings::ResolveByHash thunk
                 the thunk is at A2dLib base +0x1DC5, the real body at +0x25C70;
                 [R] goes to resolve.log, [RGAP] records hashes the pack does not
                 cover plus the engine's original text
```

What the DLL does is **patch the import tables of the modules inside the process**, replacing
the slot that points at `A2dLib-2.20A.dll!CStringManager::Add` with itself — so the engine asks it
for strings. The injection itself is done by the launcher; the DLL creates no remote threads.

Lookups come from **the base pack plus an optional override**: the hook reads
`PR2Packs\<language>.txt` first, then `PR2Packs\overrides\<language>.txt`.
A hit is substituted; a miss goes back to the engine, which uses the original text.
Entries in `overrides` with the same hash replace the base pack, which makes it
suitable for local edits you do not want to commit.

---

## The pack directory PR2Packs\

```
PR2Packs\
├─ locale.ini     which pack to use
├─ zh.txt         Simplified Chinese, 3548 entries, format: 0x<hash> = text
│                 (the filename is the language code; multiple files are allowed)
└─ overrides\
   └─ zh.txt      optional local overrides, same format; same hash wins
```

`overrides\` is optional and never appears in the launcher GUI's language list:
the GUI only enumerates `PR2Packs\*.txt`, while overrides live in a subdirectory.
The hook reads `zh.txt` first, then the exact path `overrides\zh.txt`; entries
with the same hash in the latter file win.

`locale.ini`:

```ini
language=zh          # corresponds to PR2Packs\<language>.txt and must match the filename
```

**Where the language code comes from.** `LoadEditFile()` takes the first available one in this order:

| Order | Source | Notes |
|---|---|---|
| 1 | `PR2_PACK_LANG` environment variable | Written into the child process's environment by the launcher's `--lang=xx`; affects this run only |
| 2 | `language=` in `locale.ini` | The default; the install page's "Set as game language" writes it, and the release GUI writes it after a successful launch |
| 3 | The DLL's built-in `zh` | Fallback when there is no ini at all |

Item 1 needs no IPC with the environment: the environment block the launcher passes to
`CreateProcessA` is `NULL`, meaning "inherit mine", so a single `SetEnvironmentVariableA` call is
enough for `PR2.exe` to see it. **Without `--lang` the variable doesn't exist and behaviour is
exactly as before.**

```c
PR2Launcher.exe --lang=de     runs de.txt for this launch, changes no files
PR2Launcher.exe               uses the language from locale.ini
PR2Launcher.exe --help
```

`--lang` accepts only letters, digits, and hyphens — the value is spliced into
`PR2Packs\<code>.txt`, so allowing `../` would be a path traversal; illegal values print an error
and exit.

**There is no such thing as a "base language pack".** For a hash the pack doesn't contain, the game
shows its own built-in English — the engine's main string table is the natural fallback, and nothing
extra needs preparing.

Changing text in the runtime pack **needs no rebuild**: edit `PR2Packs\zh.txt`
directly, or put the changes in `PR2Packs\overrides\zh.txt`, then restart the game.
The TOML source in the repository still goes through `quick.py` /
`compile_pack.py` to produce the runtime pack; overrides are never overwritten
by a build.

---

## ⚠ Chinese entries don't display at all — the cause is tokenization, not tags

**The engine splits words on spaces.** English is space-separated by nature: words are short and
rarely overflow. Chinese has no spaces, so a whole run of Han characters plus punctuation is laid
out as **one word**, and once it exceeds the available width of that UI control, **the whole entry
is dropped** — not truncated, not displayed at all.

```
English: Successful battles will boost your reputation more quickly with 5%.
         ^ each word is laid out separately, short

Chinese: 战斗获胜时，你的声望额外提高 5%。
         ^ the whole string is treated as one word, too wide → the entry is dropped
```

Every UI control has a different available width, and **there is no universal value** — each entry
has to be tested in game individually. Workaround: add `<n>` at a suitable point to break the line
manually, or use shorter wording.

---

## Source

The Rust workspace lives in `src\injector-rs\`:

| File | Responsibility |
|---|---|
| `pr2_common/src/lib.rs` | Shared paths, `locale.ini`, pack version checks, font completeness checks |
| `pr2_text_source/src/lib.rs` | DLL. The three hooks, whole-table replacement, missed-translation capture |
| `pr2_launcher/src/main.rs` | Launcher. Suspended start + remote injection + font backup/restore |
| `pr2_launcher_gui/src/{main,gui,packs,process,strings}.rs` | Win32 GUI. Window/layout, pack list, launcher/kill process, `ui/*.ini` |
| `ui/en.ini`, `ui/ja.ini`, `ui/zh.ini` | GUI translations, copied to `build\runtime\ui\` by the build script |

The old C++ implementation is no longer in the working tree. This page does not keep
file-level comparisons; see [Refactoring History](refactor-history.md) for the old
filenames and migration details.

### Hook safety

The Rust version drops SEH (`__try/__except`) and uses `VirtualQuery` to check whether a target
address is readable before touching candidate vtable / thunk entries. It is more conservative
than the C++ version: unreadable targets are skipped instead of forced. At worst a string shows
as empty or falls back to English; it never crashes the game.

### Known issues

- **Hook targets are tied to the game version.** The code looks up exports of
  `A2dLib-2.20A.dll` and takes the function body and the singleton at fixed offsets:
  `ResolveByHash` at `+0x25C70` (its thunk entry at `+0x1DC5`),
  `g_pStringMgr` at `+0x142084`.
  On a different game version, if these don't line up, the hooks can't find their targets and the
  localization has no effect at all.
- **Override lookup is a hash map**; `AddEdit` replaces an existing hash, so
  the last loaded entry wins. The base pack is loaded first and
  `overrides\<language>.txt` second, so overrides win.
- **Load failures were silent.** ~~When `LoadEditFile()` failed, everything returned silently~~
  Fixed: when `EditLoaded() == 0`, `InstallHook()` now writes a line
  `NO pack loaded: language 'xx' from <directory>`. Previously this failure was completely
  invisible on screen (it looked exactly like "not localized"); now the first line of the log
  tells you.

---

## Logs

Written to the game directory, all named after `PR2TextSource`:

| File | Contents |
|---|---|
| `PR2TextSource.log` | First line = the pack actually loaded and its entry count; on load failure the first line is `NO pack loaded: …` |
| `PR2TextSource_lsr.log` | Record of the vtable hook (up to 5000 entries) |
| `PR2TextSource_resolve.log` | `ResolveByHash` `[R]` records (truncated at process start, up to 8000 entries); `[RGAP]` = hashes the pack does not cover + the engine's original text, deduplicated to 2048 |
| `PR2FontPaths.log` | With `PR2_FONT_LOG=1`, logs the font paths the game reads; `PR2_FONT_LOG_ALL=1` logs every file API call |

`[RGAP]` lines in `resolve.log` are the main source of leads for filling in missing translations.

## Font backup and switching

Before replacing fonts for the first time, the launcher backs up the four original TTFs to:

```
fonts\_original\
```

Only known original sizes + SHA-256 are accepted, so even if the root directory has already been
overwritten by Noto, Noto is never mistaken for an original; the backup's hash is verified again
before restoring.

- **The originals stay in the root directory and are not overwritten**;
- Localized launch: if `fonts\<language>\` exists, the launcher sets `PR2_FONT_DIR=<language>`,
  and the DLL redirects `fonts\ARIAL.TTF` and friends to `fonts\<language>\`;
- Vanilla launch: `PR2Launcher.exe --vanilla` sets no redirection and uses the originals in the
  root directory directly; if the root directory has already been replaced, they are restored from
  `fonts\_original\` first.

Redirection only takes effect at the file API layer (`fopen` / `CreateFileA/W` / `FindFirstFileA` /
`GetFileAttributesExA`); it does not modify game files.

Log:

```bat
set PR2_FONT_LOG=1
PR2Launcher.exe --lang=zh
```

In `PR2FontPaths.log` you will see the rewritten paths such as `fonts\zh\ARIAL.TTF`.

**The first line of `PR2TextSource.log` is the only reliable indication of whether the localization
is active** — check it first once the game is running:

```
[text] pack 'zh' from C:\Games\Port Royale 2\PR2Packs: 3548 overrides
```

A line like this = the pack was found and the localization is active; the Chinese on screen comes
from it. A first line of `NO pack loaded: language 'xx' from <directory>` = there is no
`<xx>.txt` in that directory, so the DLL fell back to the engine's built-in table and the screen
shows the original English.

---

## Build

Requires Rust (rustup) and the `i686-pc-windows-msvc` target:

```bat
rustup target add i686-pc-windows-msvc
src\build_injector.bat
```

`src\injector-rs\.cargo\config.toml` pins the default target to
`i686-pc-windows-msvc`. The script runs `cargo build --release --locked`, then copies
`PR2TextSource.dll`, `PR2Launcher.exe`, `PR2LauncherGUI.exe`, and `ui\*.ini` into
`build\runtime\` at the repo root.

**The target architecture is x86** — PR2 is a 32-bit process and the hook code relies on 32-bit
calling conventions. `PR2LauncherGUI.exe` is compiled with
`#![windows_subsystem = "windows"]`, so double-clicking it does not open a console.

By hand:

```bat
cd src\injector-rs
cargo build --release
```

The artifacts land in `src\injector-rs\target\i686-pc-windows-msvc\release\`.

---

Related documents: [Translations & packs](translation-and-packs.md) · [Build & install](build-and-install.md)
