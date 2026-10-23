# Injector components

The runtime part of localizing *Port Royale 2*: **a launcher + a DLL + a language pack directory**.

**`PR2.exe` is never modified.** The launcher injects the DLL into the game process, and at runtime
the DLL takes over the engine's string lookups, feeding in the translations from `PR2Packs\`.
The original exe stays read-only throughout.

The source lives in `src\injector\`; the build script is in `src\`.

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
   │
   ├─ hook #1  IAT: CStringManager::Add
   │            when the engine registers the main string table (MISSION_NPC_GOODS_INFO),
   │            replace_table() rebuilds the whole English table as a translated table
   │
   ├─ hook #2  vtable: CW32StringManager::AddStringRes / LoadStringRes
   │
   └─ hook #3  A2dLib::LoadStringRes function body
                 catches the lookups the two hooks above don't cover;
                 and writes the hashes the pack doesn't cover, together with
                 the English the engine resolved, to PR2TextSource_gap.log
                 in the game directory, as leads for filling in translations
```

What the DLL does is **patch the import tables of the modules inside the process**, replacing
the slot that points at `A2dLib-2.20A.dll!CStringManager::Add` with itself — so the engine asks it
for strings. The injection itself is done by the launcher; the DLL creates no remote threads.

There is exactly **one** source for translation lookups — `PR2Packs\<language>.txt`. A hit is
substituted; a miss goes back to the engine, which uses the original text.

---

## The pack directory PR2Packs\

```
PR2Packs\
├─ locale.ini     which pack to use
└─ zh.txt         Simplified Chinese, 3548 entries, format: 0x<hash> = text
                  (the filename is the language code; multiple files are allowed)
```

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

Changing a translation **needs no rebuild**: edit `zh.txt`, save, restart the game.

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

| File | Responsibility |
|---|---|
| `pr2_text_source.cpp` | Main logic. The three hooks, whole-table replacement, missed-translation capture |
| `pr2_text_pack.c` | Pack loader (pure C89). INI parsing, `hash = text` parsing, UTF-8→UTF-16 |
| `pr2_launcher.cpp` | Launcher. Suspended start + remote injection |

`pr2_text_pack.c` is compiled into the DLL; it has no separate output.

### Hook safety

Every operation that can fail is wrapped in `__try/__except`. At worst the string in question shows
as empty or falls back to English; it never crashes the game.

### Known issues

- **Hook targets are tied to the game version.** The code looks up exports of
  `A2dLib-2.20A.dll` and takes the function body and the singleton at fixed offsets:
  `ResolveByHash` at `+0x25C70` (its thunk entry at `+0x1DC5`),
  `g_pStringMgr` at `+0x142084`.
  On a different game version, if these don't line up, the hooks can't find their targets and the
  localization has no effect at all.
- **`FindOverride` is a linear search**, and `AddEdit` does not deduplicate — if a pack contains a
  duplicate hash, the one written first is returned.
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
| `PR2TextSource_gap.log` | Hashes the pack doesn't cover + the English the engine resolved, for filling in translations |
| `PR2TextSource_lsr.log` | Record of the vtable hook |
| `PR2TextSource_resolve.log` | Record of `ResolveByHash` |
| `PR2FontPaths.log` | With `PR2_FONT_LOG=1`, logs the font paths the game reads; `PR2_FONT_LOG_ALL=1` logs every file API call |

`gap.log` is the main source of leads for filling in missing translations.

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
[text] pack 'zh' from C:\Games\Port Royale 2\PR2Packs  (3548 entries)
```

A line like this = the pack was found and the localization is active; the Chinese on screen comes
from it. A first line of `NO pack loaded: language 'xx' from <directory>` = there is no
`<xx>.txt` in that directory, so the DLL fell back to the engine's built-in table and the screen
shows the original English.

---

## Build

Requires Visual Studio (Desktop development with C++ workload).

```
src\build_injector.bat
```

The script locates MSVC and the Windows SDK itself; output goes to `build\` at the repo root.
**The target architecture is x86** — PR2 is a 32-bit process and the hook code relies on 32-bit
calling conventions.

You can also run the commands by hand in an "x64 Native Tools Command Prompt for VS":

```
cd src\injector
cl /nologo /MT /LD /Ox /W3 /utf-8 /D_CRT_SECURE_NO_WARNINGS ^
   pr2_text_source.cpp pr2_text_pack.c ^
   /Fe:PR2TextSource.dll /link /OUT:PR2TextSource.dll psapi.lib

cl /nologo /MT /Ox /W3 /utf-8 /wd4819 /D_CRT_SECURE_NO_WARNINGS ^
   pr2_launcher.cpp ^
   /Fe:PR2Launcher.exe /link /OUT:PR2Launcher.exe
```

Both `/utf-8` and the UTF-8 BOM on the source files are mandatory: without them, `cl` reads the
sources as code page 936 and Chinese literals are truncated at compile time (`到` becomes half a
byte), leaving every Chinese message from the launcher garbled. `/wd4819` suppresses the C4819
false positive that is still reported under `/utf-8` — the literals themselves are intact.

---

Related documents: [Translations & packs](translation-and-packs.md) · [Build & install](build-and-install.md)
