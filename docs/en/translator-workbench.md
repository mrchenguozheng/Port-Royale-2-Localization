# Translator Workbench

Translators only need to translate and proofread. They do not need Visual Studio,
Node.js, fontTools, or the game injector. The workbench is a small local Python
service that exposes only the translation page.

## Build the package

From the repository root:

```bat
python src\tools\pack\make_translator.py --lang ja --out dist\PR2Translator-ja
```

The current Python runtime is bundled by default, so the translator does **not**
need to install Python.

Custom runtime:

```bat
python src\tools\pack\make_translator.py --lang ja --out dist\PR2Translator-ja ^
    --python-dir C:\Python311
```

No bundled runtime:

```bat
python src\tools\pack\make_translator.py --lang ja --out dist\PR2Translator-ja ^
    --system-python
```

The `--python-dir` directory must contain `python.exe`.

## Contents

```
PR2Translator-ja/
├─ start.bat
├─ README.txt
├─ editor/
│  ├─ server.py           standalone stdlib server
│  └─ web/                English UI
├─ shared/core/           shared storage and validation
├─ data/
│  ├─ live/ja.toml        current language
│  └─ orig/               English reference
└─ python/                bundled by default
```

No `build/`, injector, fonts, `PR2Packs/`, glossary or install page.

Source lives in `editor/` and can be launched separately:

```bat
editor\start.bat
```

## Translator usage

1. Extract the package;
2. Double-click `start.bat`;
3. The browser opens `/translate/ja`;
4. Translate and save;
5. Close the console window to stop the service.

The workbench has no install, build or launch entry points.

> The workbench chrome is currently **English**; it is separate from the translation
> target language. The target only selects which `live/<lang>.toml` is loaded.

## Return the result

The translator returns:

```
data/live/ja.toml
```

The maintainer then:

- validates placeholders and line breaks;
- compiles the language pack;
- builds fonts;
- creates the release package;
- verifies on GOG English.

## Notes

- The workbench listens only on `127.0.0.1`;
- Python is bundled by default; only `--system-python` requires Python 3.11+;
- Git is not required;
- Other languages' translation files are not included.
