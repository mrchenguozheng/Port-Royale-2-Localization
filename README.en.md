# Port Royale 2 Localization

An external localization runtime for **Port Royale 2 (GOG English `1.1.2.3`,
+Steam English `1.1.2.3` and GOG French `1.1.2.42`)**. Language packs replace the
game's UI text; the original `PR2.exe` is not modified.

## Supported languages

| Language | In-game pack | Launcher UI |
|---|---|---|
| Simplified Chinese | `zh` | `zh` |
| Japanese | `ja` | `ja` |
| Korean | `ko` | `en` |
| Russian | `ru` | `en` |
| German | `de` | `en` |
| Spanish | `es` | `en` |
| French | `fr` | `en` |
| Italian | `it` | `en` |
| Polish | `pl` | `en` |
| English (original) | built-in | `en` |

`zh`, `ja`, `ko`, `ru`, `de`, `es`, `fr`, `it` and `pl` are the shipped
language packs. English is the original game language and the fallback when a
pack is missing. The launcher UI is available in `en`, `ja`, and `zh`.

**Translation marks: fan-made · community · AI-assisted (preview).** These
packs are unofficial: produced by the community, drafted with AI assistance and
human review. Packs adapted from a retail localization are marked `retail`
instead. Marks live in `src/packs/<lang>.toml` (`tags`), the vocabulary is in
[`pack_tags.py`](src/tools/pack/pack_tags.py), and they are copied into the
package `README.txt` and `manifest.json`.

The GOG English `1.1.2.3` build is tested through `PR2LocalizationGUI.exe`. The
Steam English `1.1.2.3` build is tested with the host-DLL proxy and a Chinese UI.
The GOG French `1.1.2.42` build is tested the same way (Polish pack, host proxy
active; the game still reports `1.1.2.42`). Other builds are out of scope.

On GOG, do **not** start `PR2.exe` directly: the loader resolves `VERSION.dll`
from `C:\Windows\SysWOW64`, so the local proxy is bypassed and the game starts
in English. Use `PR2LocalizationGUI.exe` and choose a language.

Steam does not use `VERSION.dll`. `PR2.exe` statically imports
`Ascaron.Logging-2.6.dll`; the package ships a proxy with that name under
`PR2Localization\host\` plus `PR2HostMount.ps1`. The launcher mounts it
automatically before starting the game: it verifies the original DLL
(`11,776 B`, SHA-256 `0568EC...`) and backs it up as
`Ascaron.Logging-2.6.orig.dll` and `PR2Localization\host-backup\`, then replaces
it. If the size or hash does not match, it stops without overwriting anything.
Run `PR2HostMount.ps1 -Action Mount` / `-Action Restore` manually if you prefer;
`PR2Localization.exe --restore` (or the GUI button) puts the original DLL back.

Release packages are not split by entry point: one zip
(`PR2-<lang>-<version>.zip`) works for both GOG and Steam. It always carries
the host-DLL proxy and mount script — GOG never executes them — and the
launcher detects the edition from the game directory.

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
- [Chinese project README](README.md)
- [Player guide](docs/玩家指南.md)
- [Build & install](docs/构建与安装.md)
