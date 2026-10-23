# PR2 Translator Editor

Standalone translator workbench: English UI, translation editing and placeholder
checks. It does not import the build/injector/font code and has no install page.

## Run from the repository

```bat
start.bat
```

or:

```bat
python editor\server.py --data src --web-dir editor\web --lang ja
```

`--data` points at a directory with:

```
data/
├─ live/<lang>.toml
└─ orig/en.gog_1.1.2.3.toml
```

For the repository, `src` already has `src/live` and `src/orig`, so
`--data src` works.

## Standalone package

The translator package is built with:

```bat
python src\tools\pack\make_translator.py --lang ja --out dist\PR2Translator-ja
```

It copies `editor/`, `shared/core/`, the selected language file and the English
reference, plus a Python runtime by default.

## UI language

The shipped UI is English. Strings live in `web/i18n/en.json`; static labels use
`data-i18n` keys and dynamic messages call `t("key")`.

To add another UI language:

1. Copy `web/i18n/en.json` to `web/i18n/<code>.json`;
2. Translate the values, keep the keys;
3. open `/translate/<lang>?ui=<code>`.

Missing files or keys fall back to English. The game language (`--lang`) and the
workbench UI language (`?ui=`) are independent. The **UI text** tab edits the same
JSON files directly; keys are read-only.

## API

The UI uses only:

- `GET /api/langs`
- `GET /api/count`
- `GET /api/entries`
- `GET /api/search`
- `POST /api/check`
- `POST /api/patch`
- `GET /api/ui/langs`
- `GET /api/ui?lang=<code>`
- `POST /api/ui`

Listening is fixed to `127.0.0.1`.
