# Build and install

## Entry point

For day-to-day use you only need (Python 3.11+):

```bat
start.bat
```

It will:

1. Start the workbench service on this machine;
2. Open a browser at the install page `/install`;
3. Keep a console window open showing the service log.

**It does not build automatically.** Building, deploying, and launching are all triggered by clicking buttons on the page.
Close the console window or press Ctrl+C to stop the service.

> There is also a player-facing GUI for releases, `PR2LauncherGUI.exe`; see
> [Release](release.md). That is not this development workbench.

## Installation wizard

The top of the page holds the five-step wizard under "Install and launch". Pick the target language first:

| Step | What it does |
|---|---|
| 1 Prepare the game directory | Select the game directory, or click "Select/Detect" to identify the version |
| 2 Prepare fonts | "Export original" and "Check donor"; warns when fonts are missing |
| 3 Translate content | Jump to translation editing and check how many entries are still untranslated for the target language |
| 4 Generate language pack + fonts | Calls `compile_pack` + the font build |
| 5 Install and launch | Deploy to the game directory, then launch |

The wizard only provides guidance; the cards below can still be operated on their own.

## Cards on the install page

### 1 Game directory

- Enter a path or click "Browse…";
- "Detect and remember" identifies known versions by the SHA-256 of `PR2.exe` and writes the result to settings;
- Remembered directories are listed below and can be switched to or removed;
- The status shows the version, installed language packs, and `locale.ini`.

Settings are stored by default at:

```
%LOCALAPPDATA%\PR2Localization\settings.json
```

Set the `PR2_SETTINGS` environment variable to change the location. It stores only paths and versions, never translations.

### 2 Build and deploy

| Button | Effect |
|---|---|
| Compile injector (DLL + launcher) | Calls MSVC to produce `PR2TextSource.dll`, `PR2Launcher.exe`, and `PR2LauncherGUI.exe` |
| Compile language packs | Compiles the checked languages, and checks/re-stitches fonts |
| Deploy to game directory | Copies the runtime, language packs, `ui/`, and `fonts/<language>/` |

Deployment characteristics:

- Copies files only; never modifies `PR2.exe`;
- Files with identical content are skipped by SHA-256, so they are not rewritten over and over;
- Language packs not checked in this run are removed from the game directory;
- Fonts go into `fonts/<language>/` and **do not overwrite the originals in the root directory**;
- The language pack `locale.ini` is never changed behind your back by deployment.

### 3 Launch

| Button | Effect |
|---|---|
| Language dropdown | Reads the currently available languages from `PR2Packs/*.txt` |
| Set as game language | Writes `language=` in `PR2Packs/locale.ini` |
| Launch game (injected) | Launches via `PR2Launcher.exe` with the language currently selected |
| Launch original for comparison | Launches `PR2.exe` directly, with no injection |
| Open translation editor | Switches to the translation editing page |

Note: **"Launch game" does not write `locale.ini` automatically**; click "Set as game language" if you want the choice to persist.
The release GUI, by contrast, writes it back automatically after a successful launch.

## How the language is determined

Only one language takes effect at runtime:

| Priority | Source | Scope |
|---|---|---|
| 1 | `PR2_PACK_LANG` environment variable | This launch only; set by `PR2Launcher.exe --lang=xx` |
| 2 | `language=` in `PR2Packs/locale.ini` | Persistent default |
| 3 | The DLL's built-in fallback, `zh` | When there is no ini at all |

Therefore:

- "Set as game language" on the install page = writes item 2;
- "Launch game" on the install page = passes the language for this launch only, writing no file;
- The release `PR2LauncherGUI.exe` writes item 2 after a successful launch;
- Double-clicking `PR2Launcher.exe` directly reads item 2 only;
- Running `PR2.exe` directly bypasses the launcher and performs no version check.

## Version identification

The workbench identifies known builds by the SHA-256 of `PR2.exe`:

| Version | Notes |
|---|---|
| GOG English 1.1.2.3 | Verified working |
| GOG French 1.1.2.42 | Used only as a translation reference |
| Steam English 1.1.2.3 | Has CEG; injection not verified |

Unknown versions can also be remembered, they simply have no name. Version names and hash constants live in
`src/tools/install/pr2ctl/base.py`.

## Fonts

Local development uses **fontstitch stitching**:

- Takes the original Latin font in `assets/fonts/original/` as the base;
- Appends the characters used by the current translation from the donor;
- One set per language, output to `build/fonts/<language>/`;
- Re-stitches automatically when new characters appear, with a cache marker `.stitch.json`;
- A font failure does not fail the language pack build.

The release uses the **full Noto** fonts with no stitching; see [Release](release.md) for details.

```bat
python src\tools\font\subset_fonts.py --lang zh
python src\tools\font\make_noto_fonts.py --lang zh --out <dir>
```

Stitched fonts are for local use only; do not upload or package them. See [Fonts and distribution](fonts-and-distribution.md) for details.

## Translation editing

It lives in the same workbench as the install page; switch with the tabs at the top.

- Paged editing, 100 entries per page by default;
- Edits are kept across pages; click "Save" to submit them together;
- The reference column on the right marks "this version has no such entry";
- ＋ Add language: enter a code and choose a template; this generates `src/live/<code>.toml`,
  `src/seed/<code>.toml`, and `presets/<code>.toml`;
- For a new language to appear on the install page, reload the workbench.

Language pack metadata (display name, GUI language, minimum runtime) lives in:

```
src/packs/<code>.toml
```

It is written into the language pack header at compile time. Older language packs are no longer compatible; see
[Release](release.md) for details.

## Developer commands

When you have changed translations and don't want to click through the page:

```bat
apply_patch.bat                 :: build ja + zh, deploy to the last game directory
apply_patch.bat --langs ja      :: Japanese only
apply_patch.bat --launch        :: launch right after deploying
apply_patch.bat --dry-run       :: print the plan only
```

It does the following in order:

1. Normalize translations (optional `--dep` adds the missing spaces);
2. Validate line breaks/placeholders with `check_breaks --strict`;
3. Compile language packs (font stitching included by default);
4. Deploy to the game directory;
5. Compare SHA-256 file by file.

Individual builds:

```bat
src\build_injector.bat
src\build_translation.bat
```

The unified build entry point for language packs/fonts is the library:

```python
from build_artifacts import compile_pack, build_fonts
```

Day to day, keep using `compile_pack.py` or `apply_patch.py`; there is no need to import it directly.

## The build directory

```
build\
├─ PR2TextSource.dll
├─ PR2Launcher.exe
├─ PR2LauncherGUI.exe
├─ PR2Packs\        accumulated language packs
├─ fonts\<language>\   stitched fonts
└─ font-cache\      Noto font cache
```

Everything under `build\` is an artifact; you can delete the whole thing and rebuild.

`build\PR2Packs\locale.ini` is created from the template only when it does not exist, and never overwrites the user's selected language.

## Common scripts

| Script | Responsibility |
|---|---|
| `start.bat` | Starts the local workbench service |
| `apply_patch.bat` | Build + deploy + verify |
| `src\build_injector.bat` | Compiles the DLL/launcher |
| `src\build_translation.bat` | Compiles language packs |
| `src\find_python.bat` | Locates Python |

Python entry points in `src\tools\`:

| Script | Purpose |
|---|---|
| `pack/compile_pack.py` | Compiles language packs, validates placeholders |
| `pack/build_artifacts.py` | Unified build library for language packs/fonts |
| `pack/apply_patch.py` | Builds and deploys with a single command |
| `pack/new_lang.py` | Creates a new language |
| `font/subset_fonts.py` | Stitches fonts |
| `font/make_noto_fonts.py` | Noto fonts for releases |
| `text/space_words.py` | Adds spacing for Chinese |

## Service status

The "Service status" section at the bottom of the install page shows:

- The current service pid, port, uptime, and Python version;
- Other instances in the 8777–8800 range, which can be stopped with one click;
- Endpoints: `/api/health`, `/api/server/instances`, `/api/server/stop`.

On the command line:

```bat
start.bat --status
python src\tools\install\server_status.py --stop 8779
```

Related docs: [Injection](injection.md) · [Translations and language packs](translation-and-packs.md) ·
[Architecture and refactoring](architecture.md)
