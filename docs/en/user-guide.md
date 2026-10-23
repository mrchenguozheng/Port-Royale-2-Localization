# Player Guide: Extract and Play

This document covers only **how to install and launch a release package**. It does
not cover source builds or translation work.

## 1. Check the game build

Currently supported:

```
GOG English Port Royale 2 1.1.2.3
```

Steam, GOG French and other builds are not supported. Do not deploy release packs
to them.

## 2. Download the matching language zip

Download the language you need from the project Releases page, for example:

```
PR2-zh-v0.5.0.zip
PR2-ja-v0.5.0.zip
```

One zip is one language; download several if you want several languages.

## 3. Extract into the game root

Extract **all files** next to `PR2.exe`:

```
<game directory>\
├─ PR2.exe
├─ PR2Launcher.exe
├─ PR2LauncherGUI.exe
├─ PR2TextSource.dll
├─ PR2Packs\
├─ fonts\
├─ ui\
└─ ...
```

Notes:

- Do not extract into a subfolder such as `PR2Launcher\`;
- Do not delete the four original fonts in the root `fonts\`;
- The package never overwrites `fonts\`; localized fonts go to `fonts\<lang>\`.

## 4. Run PR2LauncherGUI.exe

1. Select the target language;
2. Click **Launch selected language**.

After a successful launch, the GUI writes the choice to:

```
PR2Packs\locale.ini
```

The next launch defaults to that language.

**Do not run `PR2.exe` directly** — it will not load the language pack.

## 5. First launch backs up the original fonts

Before replacing fonts for the first time, the launcher backs up the four original
TTFs to:

```
fonts\_original\
```

After that:

- localized launch uses `fonts\<lang>\` without touching the root originals;
- `PR2Launcher.exe --vanilla` uses the root originals.

If the root fonts are not the known originals, the launcher skips the backup.

## 6. Missing fonts

If the GUI says:

```
fonts\zh\ has no TTF fonts
```

the package was not extracted completely:

1. Re-extract the whole `fonts\<lang>\` folder;
2. Verify all four files exist:

   ```
   ARIAL.TTF
   ELGRECO_.TTF
   Tiepolo_black.ttf
   Tiepolo_bold.ttf
   ```

3. Do not put fonts in the root `fonts\`;
4. Check whether antivirus quarantined them.

Launching anyway is possible, but it falls back to the original Latin fonts and CJK
text may be blank.

## 7. Switching languages

- Current language: `PR2Packs\locale.ini` → `language=`;
- Select another language in the GUI and launch again;
- Or override for one run:

  ```bat
  PR2Launcher.exe --lang=ja
  ```

  This does not write `locale.ini`.

## 8. Uninstall

Remove the files added by the package:

```
PR2Launcher.exe
PR2LauncherGUI.exe
PR2TextSource.dll
PR2Packs\<lang>.txt
fonts\<lang>\
ui\
README.txt / OFL.txt / NOTO-SOURCES.txt / RUNTIME-VERSION
```

Do not remove:

- `PR2.exe`, `.cpr`, maps, music or other game files;
- the original fonts in the root `fonts\`.

Savegames are unaffected.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| UI is still English | Ran `PR2.exe` directly, or wrong `locale.ini` | Launch through the GUI; check `PR2Packs\locale.ini` |
| CJK text is blank | Missing/incomplete fonts | Check the four TTFs in `fonts\<lang>\` |
| No language in the GUI | `PR2Packs\<lang>.txt` not in the root | Re-extract the language pack |
| Launcher window flashes | Console program; errors disappear | Run `PR2Launcher.exe` from a terminal |
| Steam does not work | Steam is unsupported | Use GOG English, or wait for future support |

For technical details see [Build & Install](build-and-install.md) and
[Release](release.md).
