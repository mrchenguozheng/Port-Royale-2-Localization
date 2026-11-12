#!/usr/bin/env python3
# coding: utf-8
"""Standalone translator editor for Port Royale 2.

The editor depends only on:
- editor/ (this server + web assets)
- shared/core/ (storage and placeholder checks)
- data/ (live/<lang>.toml and orig/en.gog_1.1.2.3.toml)

No build, injector, font or launcher code is imported.
"""
import argparse
import json
import os
import re
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from shared.core import (  # noqa: E402
    EN, FR, check_text, lang_codes, load_orig, ordered_ids, rows, save_live,
)

DATA = os.path.join(HERE, "data")
WEB = os.path.join(HERE, "web")
UI_DIR = os.path.join(WEB, "i18n")
LANG = ""            # explicit --lang override; otherwise show the chooser
PORT = 8781
UI_RE = re.compile(r"^[a-z0-9_-]{1,32}$")


def send(handler, code, body, ctype="application/json; charset=utf-8"):
    if isinstance(body, (dict, list)):
        body = json.dumps(body, ensure_ascii=False)
    data = body.encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def editable_langs():
    return lang_codes(DATA)


def resolve_lang(value):
    code = str(value or "").strip()
    return code if code in editable_langs() else None


def ui_codes():
    if not os.path.isdir(UI_DIR):
        return ["en"]
    codes = sorted(x[:-5] for x in os.listdir(UI_DIR)
                   if x.endswith(".json") and UI_RE.match(x[:-5]))
    return codes or ["en"]


def _json(path, default):
    if not os.path.isfile(path):
        return default
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def ui_load(code):
    base = _json(os.path.join(UI_DIR, "en.json"), {})
    values = dict(base) if code == "en" else _json(
        os.path.join(UI_DIR, code + ".json"), {})
    return {"lang": code, "base": base, "values": values,
            "codes": ui_codes()}


def ui_save(code, values, base):
    if not UI_RE.match(code):
        raise ValueError("invalid UI language code")
    if not isinstance(values, dict):
        raise ValueError("values must be an object")
    clean = {key: str(values.get(key, base.get(key, ""))) for key in base}
    os.makedirs(UI_DIR, exist_ok=True)
    path = os.path.join(UI_DIR, code + ".json")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(clean, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    return clean


class Handler(BaseHTTPRequestHandler):
    server_version = "PR2Translator/2"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print("[http] " + (fmt % args), flush=True)

    def do_GET(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if path.startswith("/api/"):
                return self.api_get(path, query)
            return self.static(path)
        except Exception as exc:
            return send(self, 500, {"error": str(exc)})

    def do_POST(self):
        parsed = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parsed.path)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            body = json.loads(raw.decode("utf-8"))
            return self.api_post(path, body)
        except Exception as exc:
            return send(self, 400, {"error": str(exc)})

    def static(self, path):
        if not LANG and path in ("/", "/start", "/install", "/translate", "/translate/"):
            path = "/choose.html"
        if path in ("/", "/start", "/install"):
            return self.redirect("/translate/" + LANG)
        if path == "/translate":
            return self.redirect("/translate/" + LANG)
        if path == "/translate/" + LANG or path.startswith("/translate/"):
            path = "/index.html"
        rel = path.lstrip("/") or "index.html"
        full = os.path.normpath(os.path.join(WEB, rel))
        if os.path.commonpath([full, WEB]) != WEB:
            return send(self, 404, "not found", "text/plain; charset=utf-8")
        if not os.path.isfile(full):
            return send(self, 404, "not found", "text/plain; charset=utf-8")
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
        }.get(os.path.splitext(full)[1].lower(), "application/octet-stream")
        with open(full, "rb") as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, to):
        self.send_response(302)
        self.send_header("Location", to)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def api_get(self, path, query):
        if path == "/api/health":
            return send(self, 200, {"ok": True, "lang": LANG})
        if path == "/api/langs":
            codes = editable_langs()
            return send(self, 200, {"editable": codes,
                                    "all": [EN] + codes, "base": EN,
                                    "default": LANG or ""})
        if path == "/api/count":
            lang = resolve_lang((query.get("lang") or [LANG])[0])
            if not lang:
                return send(self, 400, {"error": "unknown language"})
            return send(self, 200, {"count": len(ordered_ids(DATA, lang)),
                                    "lang": lang})
        if path == "/api/entries":
            lang = resolve_lang((query.get("lang") or [LANG])[0])
            if not lang:
                return send(self, 400, {"error": "unknown language"})
            offset = max(0, int((query.get("offset") or ["0"])[0]))
            limit = max(0, int((query.get("limit") or ["100"])[0]))
            return send(self, 200, rows(DATA, lang)[offset:offset + limit])
        if path == "/api/search":
            lang = resolve_lang((query.get("lang") or [LANG])[0])
            if not lang:
                return send(self, 400, {"error": "unknown language"})
            q = (query.get("q") or [""])[0].strip().lower()
            if not q:
                return send(self, 200, [])
            return send(self, 200, [
                row for row in rows(DATA, lang)
                if q in row["id"].lower()
                or q in row[EN].lower()
                or q in row[FR].lower()
                or q in row[lang].lower()
            ])
        if path == "/api/ui/langs":
            return send(self, 200, {"codes": ui_codes()})
        if path == "/api/ui":
            code = (query.get("lang") or ["en"])[0]
            if not UI_RE.match(code):
                return send(self, 400, {"error": "invalid language code"})
            return send(self, 200, ui_load(code))
        return send(self, 404, {"error": "unknown api"})

    def api_post(self, path, body):
        if path == "/api/check":
            hid = str(body.get("id") or "")
            text = str(body.get("text") or "")
            return send(self, 200, check_text(text, load_orig(DATA).get(hid, "")))
        if path == "/api/patch":
            lang = resolve_lang(body.get("lang"))
            if not lang:
                return send(self, 400, {"error": "unknown language"})
            updates = body.get("rows") or []
            for row in updates:
                hid = str(row.get("id") or "")
                text = str(row.get("text") or "")
                errors = [x for x in check_text(text, load_orig(DATA).get(hid, ""))
                          if x["level"] == "error"]
                if errors:
                    return send(self, 400, {
                        "error": "Placeholder/tag check failed for %s: %s" %
                                 (hid, "; ".join(x["text"] for x in errors))})
            return send(self, 200, {"ok": True,
                                    "changed": save_live(DATA, lang, updates)})
        if path == "/api/ui":
            code = str(body.get("lang") or "en")
            base = ui_load("en")["base"]
            saved = ui_save(code, body.get("values") or {}, base)
            return send(self, 200, {"ok": True, "lang": code,
                                    "values": saved, "codes": ui_codes()})
        return send(self, 404, {"error": "unknown api"})


def main():
    global DATA, WEB, UI_DIR, LANG, PORT
    ap = argparse.ArgumentParser(description="PR2 translator workbench")
    ap.add_argument("--data", default=DATA)
    ap.add_argument("--web-dir", default=WEB)
    ap.add_argument("--lang", default="")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    DATA = os.path.abspath(args.data)
    WEB = os.path.abspath(args.web_dir)
    UI_DIR = os.path.join(WEB, "i18n")
    codes = lang_codes(DATA)
    LANG = args.lang if args.lang in codes else ""
    PORT = args.port
    if not os.path.isfile(os.path.join(WEB, "index.html")):
        raise SystemExit("missing web/index.html in %s" % WEB)
    if LANG and not os.path.isfile(os.path.join(DATA, "live", LANG + ".toml")):
        raise SystemExit("missing live/%s.toml in %s" % (LANG, DATA))
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = ("http://127.0.0.1:%d/translate/%s" % (PORT, LANG)
           if LANG else "http://127.0.0.1:%d/" % PORT)
    print("PR2 Translator: %s" % url)
    print("Keep this window open. Press Ctrl+C or close it to stop.", flush=True)
    if not args.no_open:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
