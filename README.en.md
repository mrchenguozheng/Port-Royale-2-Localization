# Port Royale 2 Localization

An external localization runtime for **Port Royale 2 (GOG English `1.1.2.3` and
Steam English `1.1.2.3`)**. Language packs replace the game's UI text; the
original `PR2.exe` is not modified.

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
| English (original) | built-in | `en` |

`zh`, `ja`, `ko`, `ru`, `de`, `es`, `fr` and `it` are the shipped language
packs. English is the original game language and the fallback when a pack is
missing. The launcher UI is available in `en`, `ja`, and `zh`.

**Translation marks: fan-made · community · AI-assisted (preview).** These
packs are unofficial: produced by the community, drafted with AI assistance and
human review. Packs adapted from a retail localization are marked `retail`
instead. Marks live in `src/packs/<lang>.toml` (`tags`), the vocabulary is in
[`pack_tags.py`](src/tools/pack/pack_tags.py), and they are copied into the
package `README.txt` and `manifest.json`.

The GOG English `1.1.2.3` build is tested through `PR2LocalizationGUI.exe`. The
Steam English `1.1.2.3` build is tested with the host-DLL proxy and a Chinese UI.
GOG French and other builds are out of scope.

On GOG, do **not** start `PR2.exe` directly: the loader resolves `VERSION.dll`
from `C:\Windows\SysWOW64`, so the local proxy is bypassed and the game starts
in English. Use `PR2LocalizationGUI.exe` and choose a language.

Steam does not use `VERSION.dll`. `PR2.exe` statically imports
`Ascaron.Logging-2.6.dll`; the package ships a proxy with that name plus
`PR2HostMount.ps1`. Run `PR2HostMount.ps1 -Action Mount` once: it verifies the
original DLL (`11,776 B`, SHA-256 `0568EC...`) and backs it up as
`Ascaron.Logging-2.6.orig.dll` and `PR2Localization\host-backup\`, then replaces
it. If the size or hash does not match, it stops without overwriting anything.
Use `-Action Restore` to put the original DLL back.

Release packages are split by entry point: GOG packages
(`PR2-<lang>-gog-<version>.zip`) intentionally omit the host DLL; Steam packages
(`PR2-<lang>-steam-<version>.zip`) include the host-DLL proxy and mount script.

## Documentation

All maintained documentation is in Chinese. This page is the only English
entry point; it does not mirror the full documentation set.

- [Documentation index](docs/README.md)
- [Chinese project README](README.md)
- [Player guide](docs/玩家指南.md)
- [Build & install](docs/构建与安装.md)
