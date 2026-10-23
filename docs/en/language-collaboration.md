# Adding a Language: Collaboration Workflow

For translators who only translate and proofread (no coding), and for the
maintainer who builds and publishes. Korean `ko` is used as an example; the same
applies to other languages.

> Only GOG English `1.1.2.3` is supported. New languages must be verified on it.

## Split of work

| Task | Translator | Maintainer |
|---|---|---|
| Translation, proofreading, terminology, tone | ✅ | Can help |
| In-game verification | ✅ | ✅ |
| `src/live/<code>.toml` | ✅ | Can do |
| `src/packs/<code>.toml` | Not needed | ✅ |
| `ui/<code>.ini` | ✅ | Can do |
| Font mapping / Noto KR | Not needed | ✅ |
| Compile the pack | Optional | ✅ |
| Build/release zip | ❌ | ✅ |
| Supported builds / compatibility | ❌ | ✅ |

Rule: **the translator owns the translation and UI strings; everything else is
handled by the maintainer.**

## Translator: two ways to work

### A. Use the workbench

Requires Python 3.11+, but not Visual Studio (when the injector build artifacts
already exist).

```bat
start.bat
```

In **Translation editor**:

1. Create/select `ko` in the language dropdown (or use the language scaffolded by
   the maintainer);
2. Translate and save (written to `src/live/ko.toml`);
3. Untranslated entries fall back to English; the whole file does not have to be
   finished at once.

### B. Exchange files

The maintainer provides:

```
src/live/ko.toml
ui/ko.ini
```

The translator edits them in any UTF-8 editor and returns them. The maintainer
runs validation, builds, packages and tests.

## What translators must not change

- ids on the left of `hash =`;
- `%1`, `%2` placeholders;
- script variables such as `@D$...$`;
- tags such as `<n>`, `<c>`, `<f:...>`;
- anything under `build/` (it is regenerated and overwritten).

## Maintainer: scaffold the language

### 1. Create the translation file

```bat
python src\tools\pack\new_lang.py --new-lang ko --from en
```

Creates:

```
src/live/ko.toml
src/tools/font/fontstitch/presets/ko.toml
```

`ko.toml` is copied from English, so unchanged entries show English and can be
replaced one by one.

### 2. Add pack metadata

`src/packs/ko.toml`:

```toml
alias = "한국어"
gui = "ko"
min_runtime = 1
```

Without it, the GUI shows `ko` and falls back to English UI.

### 3. Add the launcher UI

Copy `ui/en.ini` to `ui/ko.ini` and give it to the translator.
The GUI loads it when the pack metadata says `gui = "ko"`.

### 4. Add Korean font mapping

In `LANGS` in `src/tools/font/make_noto_fonts.py`:

```python
"ko": {
    "sans": ("NotoSansKR", 400),
    "serif": ("NotoSerifKR", (700, 900)),
    "label": "Korean",
},
```

Install Noto Sans KR / Noto Serif KR on the build machine.

### 5. Build pack and fonts

```bat
python src\tools\pack\compile_pack.py --lang ko
python src\tools\font\make_noto_fonts.py --lang ko --out <dir>
```

### 6. Build the release

```bat
python src\tools\pack\make_release.py --lang ko --version v1.1.0
```

A new language is a feature, so `v1.1.0` is the usual version.

## Verification

On a clean GOG English copy:

1. Extract `PR2-ko-*.zip`;
2. Run `PR2LauncherGUI.exe`;
3. Select `한국어`;
4. Check:
   - Korean text renders;
   - no missing glyphs (especially title fonts);
   - long text/buttons are not clipped;
   - placeholders and line breaks are intact;
   - switching languages and the original launch still work.

When reporting a problem, include:

- entry hash;
- UI location;
- screenshot;
- whether it is a missing glyph, clipping or translation issue.

## Checklist before handing off

- language code fixed (e.g. `ko`);
- `ko.toml` generated with 3548 entries;
- `ui/ko.ini` exists;
- font plan decided;
- supported game build is explicitly GOG English.
