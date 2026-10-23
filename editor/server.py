#!/usr/bin/env python3
# coding: utf-8
"""Standalone translator editor for Port Royale 2.

Only the translation page is served. No build, deploy, font or launcher code is
imported; this server uses the Python standard library only.

    python editor\\server.py --data editor\\data --lang ja
"""
import argparse
import json
import os
import re
import sys
import threading
import tomllib
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
WEB = os.path.join(HERE, "web")
LANG = "ja"
PORT = 8781

EN = "en.gog_1.1.2.3"
RE_SCRIPT = re.compile(r"@[A-Za-z]\$[A-Za-z_][A-Za-z_0-9]*\$")
RE_POS = re.compile(r"%\d+")
RE_PAD = re.compile(r"%(0?\d+)%(?!\d)")
RE_FONT = re.compile(r"<f:[^>]*>")
RE_TAG = re.compile(r"<[^>]*>")
RE_PLACEHOLDER = re.compile(r"^0x[0-9a-f]{8} \| ", re.I)


def load_toml(path):
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def live_path(lang):
    return os.path.join(DATA, "live", lang + ".toml")


def orig_path():
    p = os.path.join(DATA, "orig", EN + ".toml")
    if not os.path.isfile(p):
        p = os.path.join(DATA, "orig", "en.toml")
    return p


def load_live(lang):
    p = live_path(lang)
    return load_toml(p) if os.path.isfile(p) else {}


def load_orig():
    p = orig_path()
    return load_toml(p) if os.path.isfile(p) else {}


def lang_codes():
    d = os.path.join(DATA, "live")
    if not os.path.isdir(d):
        return []
    return sorted(x[:-5] for x in os.listdir(d)
                  if x.endswith(".toml") and not x.startswith("_")
                  and x != "keep_original.toml")


def ordered_ids():
    live = load_live(LANG)
    orig = load_orig()
    ids = list(orig.keys())
    ids += [x for x in live.keys() if x not in orig]
    return ids


def rows():
    live = load_live(LANG)
    orig = load_orig()
    out = []
    for hid in ordered_ids():
        out.append({
            "id": hid,
            EN: orig.get(hid, ""),
            LANG: live.get(hid, ""),
        })
    return out


def tokens(text):
    text = RE_FONT.sub("", text)
    text = RE_TAG.sub("", text)
    text = RE_PAD.sub(r"%\1", text)
    return set(RE_SCRIPT.findall(text)) | set(RE_POS.findall(text))


def tag_counts(text):
    text = RE_FONT.sub("", text)
    return {t: text.count(t) for t in set(RE_TAG.findall(text))}


def check_text(hid, text, english):
    out = []
    if not text:
        return [{"level": "warn", "text": "Empty; the game will show English."}]
    if RE_PLACEHOLDER.match(text):
        return [{"level": "warn", "text": "Untranslated placeholder."}]
    a, b = tokens(english), tokens(text)
    missing, extra = a - b, b - a
    if missing:
        out.append({"level": "warn",
                    "text": "Missing placeholder(s): " + " ".join(sorted(missing))})
    if extra:
        out.append({"level": "error",
                    "text": "Extra placeholder(s): " + " ".join(sorted(extra))})
    ta, tb = tag_counts(english), tag_counts(text)
    for tag in sorted(set(ta) | set(tb)):
        if tb.get(tag, 0) > ta.get(tag, 0):
            out.append({"level": "error", "text": "Extra tag: " + tag})
        elif tb.get(tag, 0) < ta.get(tag, 0):
            out.append({"level": "warn", "text": "Missing tag: " + tag})
    return out


def save_rows(updates):
    live = load_live(LANG)
    orig = load_orig()
    by_lower = {k.lower(): k for k in live}
    changed = 0
    for row in updates:
        hid = str(row.get("id") or "")
        key = by_lower.get(hid.lower())
        if not key:
            continue
        text = str(row.get("text") or "")
        if live[key] != text:
            live[key] = text
            changed += 1
    ids = list(orig.keys()) + [x for x in live.keys() if x not in orig]
    lines = []
    for hid in ids:
        if hid in live:
            lines.append("%s = %s\n" % (
                json.dumps(hid, ensure_ascii=False),
                json.dumps(live[hid], ensure_ascii=False)))
    with open(live_path(LANG), "w", encoding="utf-8", newline="\n") as fh:
        fh.writelines(lines)
    return changed


def send(handler, code, body, ctype="application/json; charset=utf-8"):
    if isinstance(body, (dict, list)):
        body = json.dumps(body, ensure_ascii=False)
    data = body.encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


class Handler(BaseHTTPRequestHandler):
    server_version = "PR2Translator/1"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

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
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) if n else b"{}"
            body = json.loads(raw.decode("utf-8"))
            return self.api_post(path, body)
        except Exception as exc:
            return send(self, 400, {"error": str(exc)})

    def static(self, path):
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
            langs = lang_codes()
            return send(self, 200, {
                "editable": langs, "all": [EN] + langs, "base": EN})
        if path == "/api/count":
            lang = (query.get("lang") or [LANG])[0]
            if lang != LANG:
                return send(self, 400, {"error": "unknown language"})
            return send(self, 200, {"count": len(ordered_ids())})
        if path == "/api/entries":
            lang = (query.get("lang") or [LANG])[0]
            if lang != LANG:
                return send(self, 400, {"error": "unknown language"})
            off = int((query.get("offset") or ["0"])[0])
            lim = int((query.get("limit") or ["100"])[0])
            return send(self, 200, rows()[max(0, off):max(0, off) + max(0, lim)])
        if path == "/api/search":
            lang = (query.get("lang") or [LANG])[0]
            if lang != LANG:
                return send(self, 400, {"error": "unknown language"})
            q = (query.get("q") or [""])[0].strip().lower()
            if not q:
                return send(self, 200, [])
            return send(self, 200, [
                r for r in rows()
                if q in r["id"].lower() or q in r[EN].lower() or q in r[LANG].lower()
            ])
        return send(self, 404, {"error": "unknown api"})

    def api_post(self, path, body):
        if path == "/api/check":
            hid = str(body.get("id") or "")
            text = str(body.get("text") or "")
            en = load_orig().get(hid, "")
            return send(self, 200, check_text(hid, text, en))
        if path == "/api/patch":
            updates = body.get("rows") or []
            for row in updates:
                hid = str(row.get("id") or "")
                text = str(row.get("text") or "")
                en = load_orig().get(hid, "")
                errs = [x for x in check_text(hid, text, en)
                        if x["level"] == "error"]
                if errs:
                    return send(self, 400, {
                        "error": "Placeholder/tag check failed for %s: %s" %
                                 (hid, "; ".join(x["text"] for x in errs))})
            return send(self, 200, {"ok": True, "changed": save_rows(updates)})
        return send(self, 404, {"error": "unknown api"})


def main():
    global DATA, WEB, LANG, PORT
    ap = argparse.ArgumentParser(description="PR2 translator workbench")
    ap.add_argument("--data", default=DATA)
    ap.add_argument("--web-dir", default=WEB)
    ap.add_argument("--lang", default="")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()
    DATA = os.path.abspath(args.data)
    WEB = os.path.abspath(args.web_dir)
    LANG = args.lang or ((lang_codes() or ["ja"])[0])
    PORT = args.port
    if not os.path.isfile(os.path.join(WEB, "index.html")):
        raise SystemExit("missing web/index.html in %s" % WEB)
    if not os.path.isfile(live_path(LANG)):
        raise SystemExit("missing %s" % live_path(LANG))
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = "http://127.0.0.1:%d/translate/%s" % (PORT, LANG)
    print("PR2 Translator: %s" % url)
    if not args.no_open:
        threading.Timer(0.3, lambda: webbrowser.open(url)).start()
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
