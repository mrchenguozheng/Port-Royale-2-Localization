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

It copies `editor/server.py`, `editor/web`, the selected language file and the
English reference, plus a Python runtime by default.

## API

The UI uses only:

- `GET /api/langs`
- `GET /api/count`
- `GET /api/entries`
- `GET /api/search`
- `POST /api/check`
- `POST /api/patch`

Listening is fixed to `127.0.0.1`.
