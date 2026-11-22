# Port Royale 2 Localization

An external localization runtime for **Port Royale 2 (GOG English `1.1.2.3`,
Steam English `1.1.2.3` and GOG French `1.1.2.42`)**. Language packs replace the
game's UI text; the original `PR2.exe` is not modified.

## Supported languages

| Package | In-game packs | Launcher UI |
|---|---|---|
| `PR2-zh` | `zh` | `zh` |
| `PR2-ja` | `ja` | `ja` |
| `PR2-ko` | `ko` | `ko` |
| `PR2-ru` | `ru` | `ru` |
| `PR2-pl` | `pl` | `pl` |
| `PR2-latin` | `de`, `es`, `fr`, `it` | `de` |
| English (original) | built-in | `en` |

`zh`, `ja`, `ko`, `ru`, `de`, `es`, `fr`, `it` and `pl` are the shipped
language packs. English is the original game language and the fallback when a
pack is missing. Each package ships exactly one `ui.default.ini` in its package
language; switching the game locale inside `PR2-latin` does not switch the
launcher UI. Source has nine `ui.<lang>.ini` files and `ui.default.ini` is
generated at build time from `ui.zh.ini`.

**Launcher UI has no native-speaker review.** The nine launcher translations
were drafted with AI and only checked mechanically (same keys, same
placeholders). They have not been proofread line by line by native speakers.
If you are a native speaker of one of these languages and want to help, please
open an issue with a screenshot, the current line and your suggested wording.
The in-game packs are unofficial too: produced by the community, drafted with
AI assistance and human review. Packs adapted from a retail localization are
marked `retail` instead. Marks live in `src/packs/<lang>.toml` (`tags`), the
vocabulary is in
[`pack_tags.py`](src/tools/pack/pack_tags.py), and they are copied into the
package `README.txt` and `manifest.json`.

## Requirements

**Windows 10 or Windows 11 only.** Windows 7 is not supported or tested.
The game itself is 32-bit; no Python, Rust, PowerShell or script-execution
policy is required on the player side. Verified game builds are GOG English
`1.1.2.3`, Steam English `1.1.2.3` and GOG French `1.1.2.42`; other builds are
out of scope.

The GOG English `1.1.2.3` build is tested through `PR2LocalizationGUI.exe`. The
Steam English `1.1.2.3` build is tested with the host-DLL proxy and a Chinese UI.
The GOG French `1.1.2.42` build is tested the same way (Polish pack, host proxy
active; the game still reports `1.1.2.42`).

On GOG, starting `PR2.exe` directly only shows the translation once the host
proxy has been mounted; the GUI does that before launching. The old
`VERSION.dll` route is gone (Windows resolves that name from `SysWOW64`).

Steam does not use `VERSION.dll`. `PR2.exe` statically imports
`Ascaron.Logging-2.6.dll`; the package ships a proxy with that name under
`PR2Localization\host\`. The launcher mounts it automatically before starting
the game, in-process: it verifies the original DLL (`11,776 B`, SHA-256
`0568EC...`), backs it up as `Ascaron.Logging-2.6.orig.dll` and
`PR2Localization\host-backup\`, then replaces it atomically. If the size or
hash does not match, it stops without overwriting anything. No PowerShell or
script execution is involved, so policy-locked machines work too.
`PR2Localization.exe --restore` (or the GUI button) puts the original DLL back;
`--mount` only mounts without starting the game.

Release packages are not split by entry point: one zip
(`PR2-<lang>-<version>.zip`) works for both GOG and Steam. It always carries
the host-DLL proxy — GOG never needs a separate script — and the launcher
detects the edition from the game directory.

Versions are visible in three places, all from the same `-Version` value: the
GUI subtitle (`runtime v1 · v1.0.0 (c8aa6e3)`), each language list entry
(`简体中文 · v1.0.0` — read from the pack's `# pack-meta version=` header), and
`PR2Localization.exe --version`. Dev builds print `dev (c8aa6e3+dirty)`.

What changed inside the language pack is visible too. The status box has a
second line with entry count, untranslated count and a content digest
(`3590 entries · 0 untranslated · digest 9cfa2931c1c2`). The digest covers the
translated lines only, so re-packing the same text under a new version number
keeps it unchanged, while editing one line changes it. `README.txt` in the
package root and `manifest.json` (`translations[].delta`) additionally state
how many entries were added, changed or removed since the previous
`release-v*` tag.

## Documentation

All maintained documentation is in Chinese. This page is the only English
entry point; it does not mirror the full documentation set.

- [Documentation index](docs/README.md)
- [Runtime contract](docs/运行契约.md) — package layout, host mount, UI language
- [Chinese project README](README.md)
- [Player guide](docs/玩家指南.md)
- [Build & install](docs/构建与安装.md)
