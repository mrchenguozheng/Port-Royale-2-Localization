# Translator Workbench

Translators only need to translate and proofread. They do not need Visual Studio,
Node.js, fontTools, or the game injector. The workbench is a small local Python
service that exposes only the translation page.

## Build the package

From the repository root:

```bat
python src\tools\pack\make_translator.py --lang ja --out dist\PR2Translator-ja
```

To bundle a Python runtime so the translator does not need to install Python:

```bat
python src\tools\pack\make_translator.py --lang ja --out dist\PR2Translator-ja ^
    --python-dir C:\Python311
```

The `--python-dir` directory must contain `python.exe`.

## Contents

```
PR2Translator-ja/
├─ start.bat
├─ README.txt
├─ src/
│  ├─ editor/
│  │  ├─ server.py
│  │  └─ dist/             prebuilt frontend
│  ├─ tools/               translation, validation, terminology
│  ├─ live/ja.toml         current language
│  ├─ orig/                English reference
│  ├─ seed/                initial text
│  └─ find_python.bat
└─ glossary/               terminology
```

No `build/`, injector, fonts, `PR2Packs/` or install page.

## Translator usage

1. Extract the package;
2. Double-click `start.bat`;
3. The browser opens `/translate/ja`;
4. Translate and save;
5. Close the console window to stop the service.

Only the translation editor is shown. Build/deploy/launch endpoints return 403.

## Return the result

The translator returns:

```
src/live/ja.toml
```

The maintainer then:

- validates placeholders and line breaks;
- compiles the language pack;
- builds fonts;
- creates the release package;
- verifies on GOG English.

## Notes

- The workbench listens only on `127.0.0.1`;
- Python 3.11+ is required unless a runtime is bundled;
- Git is not required;
- Other languages' translation files are not included.
