# Port Royale 2 Localization

An external localization runtime for **Port Royale 2 (GOG English `1.1.2.3` and
Steam English, experimental)**. Language packs replace the game's UI text; the
original `PR2.exe` is not modified.

## Supported languages

| Language | In-game pack | Launcher UI |
|---|---|---|
| Simplified Chinese | `zh` | `zh` |
| Japanese | `ja` | `ja` |
| English (original) | built-in | `en` |

`zh` and `ja` are the shipped language packs. English is the original game
language and the fallback when a pack is missing. The launcher UI is available
in `en`, `ja`, and `zh`.

The GOG English `1.1.2.3` build is tested. Steam English is experimental: the
`VERSION.dll` proxy loading chain is built, but it still needs an in-game check.
GOG French and other builds are out of scope.

With this chain, the game loads `PR2TextSource.dll` from its own directory through
a local `VERSION.dll` proxy; no launcher injection is required. `PR2LauncherGUI.exe`
remains available as a fallback if another mod already uses `VERSION.dll`.

## Documentation

All maintained documentation is in Chinese. This page is the only English
entry point; it does not mirror the full documentation set.

- [Documentation index](docs/README.md)
- [Chinese project README](README.md)
- [Player guide](docs/玩家指南.md)
- [Build & install](docs/构建与安装.md)
