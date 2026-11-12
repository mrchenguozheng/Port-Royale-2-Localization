# Editor HTTP API Contract (for agents)

This document is for agents that read/write translations or run checks,
builds and deployments. It covers the routes actually registered by
`src/editor/server.py` (41 at present), including routes used by the
frontend itself. **It is not a public internet API**; the server binds to
loopback only.

## Start and connect

```powershell
python src\editor\server.py --port 8777 --no-open
```

- Base URL `http://127.0.0.1:8777`; default port `8777`.
- Bind `127.0.0.1` only. The API writes repository files — never expose it
  on `0.0.0.0`.
- No authentication, no CORS. `token` only distinguishes editor instances;
  it comes from `PR2_EDITOR_TOKEN` and defaults to an empty string. It is
  not an access credential.
- UTF-8 JSON everywhere. GET parameters go in the query string; POST must
  send a JSON **object** — no form data, arrays or empty body.
- Successful responses use HTTP 200. Business failures may also use 200;
  check the `ok` field.
- Failures use `{"detail": "message"}` with 400 / 404 / 500. A body that is
  not valid JSON, or not an object, returns 400.
- Unknown routes return 404 `{"detail": "unknown api: ..."}`. POST parses
  the body first, so an invalid body yields 400 before the 404.

Confirm the service and data root first:

```text
GET /api/health
→ {"app":"pr2-editor","pid":…,"port":8777,"token":"","started":…,"uptime":…,
   "python":"3.13…","root":"…","dist_mtime":…}
```

`app` must be `pr2-editor`. If another service owns the port, stop there.

## Data model

An entry id is an 8-digit hexadecimal hash written as `0xc46f793a`. It is
the only key for one text; two entries with identical text can still have
different ids.

A language code is the file name of `src/translations/<code>.toml`. The
base language `en.gog_1.1.2.3` holds the English source and is read-only.
`GET /api/langs` returns:

```json
{"editable": ["ja", "zh"],
 "all": ["en.gog_1.1.2.3", "fr.gog_1.1.2.42", "ja", "zh"],
 "base": "en.gog_1.1.2.3"}
```

Only codes in `editable` are writable; other codes in `all` are reference
languages and writes are rejected with 400.

An entry row (returned by `/api/list`, `/api/entries`, `/api/search`):

```json
{"id":"0xc46f793a","ctx":"","en.gog_1.1.2.3":"Thank you …","zh":"谢谢你 …","ja":"…"}
```

Every language code is a key on the row. `missing` appears only when a
reference language lacks this entry; its value is an array of missing
language codes. `ctx` is the context column from the data and is usually
empty.

List endpoints truncate text: `/api/list` at 60 characters, `/api/ids` at
80 for English and 60 for the translation; `/api/entries` and
`/api/search` return full text. In `/api/list` and `/api/ids` the key `zh`
is fixed but its value comes from the request's `lang` (pass `ja` and that
field is Japanese). Do not treat it as a language-code key.

## Write rules (mandatory for agents)

1. Modify only `src/translations/<lang>.toml`. Each line is
   `"0x…" = "text"`. Keep the existing file order; **never reorder, add or
   remove ids**.
2. Write endpoints are atomic (temp file + replace) and update only the
   submitted ids; everything else is preserved. Do not rewrite the whole
   file with a text editor.
3. Before saving, `POST /api/patch` compares placeholder **counts**
   (`@X$…$`, `%02`, `%2`) between English and the translation. A mismatch
   rejects the whole batch with 400 and lists at most 10 problems. `%02`
   and `%2` are distinct tokens; never normalize them.
4. Tags (`<n>`, `<o:…>`, `<t>`, …) are reported as extra/missing by
   `/api/check`, but `/api/patch` does not block tag differences. Call
   `/api/check` before submitting.
5. An empty translation is valid and falls back to English in game.
   `POST /api/seed` may set one entry back to an empty string.
6. Do not judge layout with pixel or font width. The editor only handles
   the text layer; real line breaks are verified in game.

## 1. Meta (4 routes)

| Method | Path | Parameters | Returns |
|---|---|---|---|
| GET | `/api/health` | none | Health object above: pid, port, start time, Python version, repo root, frontend mtime |
| GET | `/api/server/instances` | none | `{"current":port,"instances":[health…]}`; scans 8777–8800 only, may be empty |
| POST | `/api/server/stop` | `{"port": int}` | `{"ok":bool,"port":int}`; cannot stop port 0 or the current port |
| POST | `/api/shutdown` | none | Returns `{"ok":true}` first, then exits after ~0.2 s |

`/api/server/stop` calls the target instance's `/api/shutdown` instead of
killing a process. If no editor runs on that port it returns `ok:false`.

## 2. Entry reads and checks (14 routes)

| Method | Path | Parameters | Returns |
|---|---|---|---|
| GET | `/api/context-batch` | `ids` (comma-separated, first 200 used), `lang` | `{id: context}`; unknown ids omitted |
| GET | `/api/rule-trace` | `id`, `lang` (both required) | `{"id","stages":[{"key","label","text"}]}`; 404 if missing |
| GET | `/api/seed` | `id`, `lang` (both required) | `{"text": current translation}`; 404 if the id is not in the file |
| GET | `/api/entry-info` | `id`, `lang` | Placeholder/tag/length statistics, see below; 404 if missing |
| GET | `/api/list` | `lang` | Short previews of all rows `[{id,en,zh}]` (60 chars each) |
| GET | `/api/ids` | `q`, `limit` (default 20), `lang` | `{"ids":[{id,en,zh}],"count":total hits}`; `q` matches an id substring |
| GET | `/api/find` | `id`, `lang` | `{"id","index","count"}`; index is file order, -1 if missing |
| GET | `/api/count` | `filter` (`all`/`attention`), `lang` | `{"count","ids":[…],"filter","lang"}` |
| GET | `/api/terms` | `lang` | `{"count","issues":{id:[message…]},"lang"}`; adds `note` when no glossary |
| GET | `/api/entries` | `offset`, `limit`, `filter`, `lang` | Array of entry rows; `limit<=0` returns all, `offset<0` treated as 0 |
| GET | `/api/search` | `q`, `filter`, `lang` | Array of entry rows; empty `q` returns `[]`, no pagination limit |
| POST | `/api/check` | `{"id","text","lang"}` | `[{level:"error"|"warn","text":message}]`; unknown id returns `[]` |
| POST | `/api/seed` | `{"id","lang","text"}` | `{"ok":true,"text"}`; 404 if no language file or id |
| POST | `/api/patch` | `{"lang","rows":[{"id","text"}]}` | `{"ok":true,"written":rows in file,"changed":submitted rows}` |

### Details

- When `lang` is omitted, read endpoints use the first `editable`
  language (currently `ja`). Write endpoints have no default; pass it
  explicitly.
- `filter=attention` is the union of placeholder/tag problems, empty
  translations and terminology mismatches, in file order. `/api/terms`
  reports terminology mismatches only; the two scopes differ.
- `context` shape:

```json
{"id":"0x…","category":"UI label / short title","reasons":["…"],
 "placeholders":[{"token":"@g$TotalPrice$","meaning":""}],
 "tags":["Line break"],
 "en":"…","zh":"…",
 "neighbors":[{"id":"0x…","en":"…","zh":"…"}]}
```

- `entry-info` shape:

```json
{"placeholders":[{"token":"…","meaning":"…"}],
 "counts":[{"token":"%02","en":1,"zh":2}],
 "mismatch":["%02"],
 "tags":["…"],
 "missing":["tokens in English but not in the translation"],
 "extra":["tokens in the translation but not in English"],
 "used":["tokens present in the translation"],
 "spaces":3,"clean_spaces":3,"extra_spaces":0,
 "length":42,"en_len":57}
```

`missing`/`extra` are set-based (occurrence counts ignored); only `counts`
carries counts. `extra_spaces` is always 0: spaces added by the engine are
build artifacts, not part of the translation layer.

- `rule-trace` has four stages for `zh` (“translation → punctuation
  normalization → conjunction spacing → person/town spacing, before
  padding”) and two for other languages (“translation → normalization”).
  It reproduces the translation layer only; it does not start a tokenizer,
  so final padding is not included.
- `POST /api/check` takes new, unsaved text and does not write. Messages
  are always Chinese (matching the frontend).
- `POST /api/seed` is a **single-row replacement** and writes immediately.
  Good for reverting one entry; use `/api/patch` for batches.
- For `/api/patch`, `written` is the final number of rows written to the
  file (3548 in the current base) and `changed` is the number of submitted
  ids; `changed` does not mean values actually changed.

## 3. Languages and glossaries (7 routes)

| Method | Path | Parameters | Returns |
|---|---|---|---|
| GET | `/api/langs` | none | `{"editable","all","base"}` |
| GET | `/api/lang-summary` | `lang` (default zh) | `{"lang","total","todo","done"}` |
| GET | `/api/lang-exists` | `code` | Availability report for a new language, see below |
| GET | `/api/hash-rules` | `id` | `{"id","rules":{"skip_terms":[…]}}` |
| POST | `/api/placeholder-meaning` | `{"lang","id","token","meaning"}` | `{"ok":true,"meanings":{token:meaning}}` |
| POST | `/api/hash-rule` | `{"id","term","skip":bool}` | `{"ok":true,"rules":{…}}` |
| POST | `/api/newlang` | `{"code","from"}` | `{"ok":true,"code","from","aligned","dropped","filled",…}` |

- `lang-summary.todo` counts entries that are empty **or identical to
  English**, not just empty strings.
- `lang-exists` may include `exists`, `reference`, `path` and `reason`.
  `ok:true` means the code is usable. The format is “letter first, then
  letters/digits/`-`/`_`, max 16”. Existing codes and reference languages
  return `ok:false`.
- `placeholder-meaning` writes `glossary/placeholder_meanings.toml`.
  `meaning:null` removes the override; an empty string keeps an empty
  meaning. Missing `id` or `token` returns 200 `{"ok":false,"error":…}`
  and writes nothing.
- `hash-rule` writes `glossary/hash_rules.toml`. `skip:true` adds the term
  to this entry's `skip_terms`; `false` removes it. Missing `id`/`term`
  returns `ok:false`.
- `newlang` copies the `from` template and aligns it to the base language
  id order. `aligned` means the template was already aligned; `dropped`
  counts template ids not in the base; `filled` counts base ids missing
  from the template and filled from English. An existing code returns 400
  and is never overwritten. The response may include `presets` (font
  preset generation) or `presets_error`.
- `skip_terms` affects only `/api/terms` and the terminology part of
  `attention`; it does not change placeholder/tag checks.

## 4. Install, build and deploy (16 routes)

| Method | Path | Parameters | Returns |
|---|---|---|---|
| GET | `/api/start/running` | none | `{"running":bool,"procs":[{"name","pid"}]}` |
| GET | `/api/font-status` | none | Font readiness, see below |
| GET | `/api/start/status` | none | Current game directory status, see below |
| GET | `/api/start/dirs` | none | `{"dirs":[{sha,dir,label,last_used,current,valid}]}` |
| GET | `/api/start/job` | none | Background job snapshot `{running,lines,done,ok,kind,error}` |
| POST | `/api/font/export` | `{"dir": game dir}` | Runs `extract_fonts.py`, returns `{ok,output,status}` |
| POST | `/api/start/pick` | none | Opens the native folder dialog; `{ok,path}` or `{ok:false,"error":"已取消"}` |
| POST | `/api/start/use` | `{"sha"}` | `{"ok":true, …start_status}` |
| POST | `/api/start/forget` | `{"sha"}` | `{"ok":true,"dirs":[…]}` |
| POST | `/api/start/dir` | `{"path"}` | `{"ok":true, …start_status}` |
| POST | `/api/start/build-injector` | none | `{"ok":true,"kind":"injector"}`, runs in background |
| POST | `/api/start/build` | `{"langs":["zh",…]}` | `{"ok":true,"kind":"build"}`, runs in background |
| POST | `/api/start/deploy` | `{"langs":["zh",…]}` (optional) | `{"ok":true,"kind":"deploy"}`, runs in background |
| POST | `/api/start/lang` | `{"lang"}` | `{"ok":bool,"lang", …start_status}` |
| POST | `/api/start/kill` | none | `{"ok":bool,"message","procs":[…]}` |
| POST | `/api/start/launch` | `{"lang"?, "vanilla"?}` | `{"ok":bool,"message":…}` |

### Status shapes

`/api/start/status` before a directory is selected:

```json
{"dir":"","valid":false,"langs":["ja","zh"]}
```

With a valid game directory:

```json
{"dir":"…","valid":true,"langs":["ja","zh"],
 "version":"…","sha":"…",
 "patches":[{"name":"…","exists":true}],
 "packs":["zh"],
 "locale":"zh"}
```

`version`, `sha`, `patches`, `packs` and `locale` appear only when
`valid:true`.

`/api/font-status`:

```json
{"ok":bool,"fonttools":bool,
 "base":{"dir":"…","missing":["…"],"total":…},
 "languages":[{"lang":"zh","donors":[{"path":"…","exists":true}],"built":…,"total":…}],
 "problems":["…"],
 "presets_dir":"…"}
```

### Background jobs

`build-injector` / `build` / `deploy` only **start** a job and return
immediately. Progress comes from `/api/start/job`:

```json
{"running":true,"lines":["…"],"done":false,"ok":false,"kind":"build","error":""}
```

Poll until `running:false`. `done:true` means the thread finished, `ok`
means success, and a non-empty `error` means an exception. `lines` keeps
at most 500 lines. Only one job runs at a time; a second request returns
`{"ok":false,"error":"已有任务在运行"}`.

### Cautions

- `/api/start/pick` opens a Windows folder dialog and can block for up to
  180 seconds. Unattended agents should not call it; pass a known path to
  `/api/start/dir` instead.
- `build` requires a non-empty subset of `available_langs()`; otherwise it
  returns `ok:false`. `deploy` without languages deploys the available
  languages.
- `deploy`, `start/lang` and `start/launch` require a valid game directory.
- `/api/start/kill` terminates `PR2.exe` / `PR2Launcher.exe`;
  `launch` with `vanilla:true` starts the uninjected original.
- `/api/font/export` writes `assets/fonts/original/` and extracts fonts
  from the game directory; an empty `dir` returns `ok:false`.
- These routes have real side effects (file writes, processes, changes to
  `locale.ini`). Agents should call them only when the user explicitly
  asks for build/deploy/launch, and never as connectivity probes.

## Typical agent flow

Read and translate a batch:

1. `GET /api/langs` to confirm writable languages.
2. `GET /api/count?filter=all&lang=zh` for id order, or
   `filter=attention` for the pending set only.
3. `GET /api/entries?offset=0&limit=50&filter=all&lang=zh` for full text.
4. `POST /api/check` per entry; resolve `error`/`warn`.
5. Put this batch's `{"id","text"}` into `rows` and call
   `POST /api/patch` once.
6. Spot-check with `GET /api/entry-info` or `GET /api/seed`.

Single-row edit:

```http
POST /api/seed
Content-Type: application/json

{"id":"0xc46f793a","lang":"zh","text":"new translation"}
```

Batch submit:

```http
POST /api/patch
Content-Type: application/json

{"lang":"zh","rows":[{"id":"0xc46f793a","text":"甲"},{"id":"0x384261bc","text":"乙"}]}
```

If any write endpoint returns 400, **do not retry the same batch**; fix the
placeholders or ids from `detail`, then check again.
