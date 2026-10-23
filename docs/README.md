# Documentation Index

This is not the project introduction — it answers "which document do I need?".
English translations cover the core workflow; specialist analysis documents remain
Chinese-only for now.

[中文文档索引](README.zh-CN.md) · [日本語](README.ja.md) · [Project README](../README.en.md)

> **Supported game build: GOG English `1.1.2.3` only.** Other builds are out of scope.

## Players

| Document | Contents |
|---|---|
| [Player guide](en/user-guide.md) | Download, extract, launch, uninstall, troubleshooting |

## Build and release

| Document | When to read |
|---|---|
| [Release](en/release.md) | Per-language zips, package layout, font licenses, GitHub Releases |
| [Build & Install](en/build-and-install.md) | Workbench, install wizard, build/deploy/launch, scripts |
| [Fonts & distribution](en/fonts-and-distribution.md) | Whether Noto / stitched fonts may be redistributed |
| [New language fonts](en/new-language-fonts.md) | Fonts and tools required for a new language |

## Development

| Document | When to read |
|---|---|
| [Architecture](en/architecture.md) | Layers, file contracts, refactor record, remaining boundaries |
| [Injector](en/injection.md) | How the DLL hooks text lookups and how the launcher injects it |
| [Translations & packs](en/translation-and-packs.md) | TOML format, `hash = text`, editor workflow |
| [New language](en/new-language.md) | Add a language from scratch |
| [Language collaboration](en/language-collaboration.md) | Translator/maintainer split, handoff and verification |

## Translation notes

| Document | Contents |
|---|---|
| [Speaker tiers](en/speaker-tiers.md) | Which lines identify a speaker, which are guesses |
| [Tone proposals](en/tone-proposal.md) | 41 confident speakers plus entries for review |
| [Translation limits](en/translation-limits.md) | What cannot be fixed, verified coverage, hook trade-offs |
| [Pending](en/pending.md) | Steam, untested French build, hook offsets |

## Specialist / Chinese-only

These are detailed analysis documents kept in Chinese:

| Document | Contents |
|---|---|
| [语音清单](语音清单.md) / [语音映射](语音映射.md) | Voice inventory and hash mapping |
| [中文分词方案](中文分词方案.md) | Chinese tokenization and spacing |
| [中文文本改动对比](中文文本改动对比.md) | Historical Chinese text diffs |
| [CSV data](csv/README.md) | Analysis, voice, review and generated CSV files |

## Current contracts

- Game language: `PR2Packs/locale.ini` → `language=`
- Pack display name / GUI language / minimum runtime: `PR2Packs/<lang>.txt`
  header (`# pack-meta alias=…`, `gui=…`, `min_runtime=…`)
- Fonts: four TTF files in `fonts/<lang>/`; never overwrite the originals in `fonts/`
- Launcher UI translations: `ui/<lang>.ini`
- Runtime version: `src/injector/pr2_version.h`; `RUNTIME-VERSION` in release zips

See [Architecture](en/architecture.md) for the full contract.
