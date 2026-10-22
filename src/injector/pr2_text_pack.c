/* pr2_text_pack.c -- language pack loader (multi-language, pure C89)
 *
 * Folder layout next to the game exe:
 *
 *   PR2Packs/
 *     locale.ini      <- which language to load, plus options
 *     zh.txt          <- Chinese overrides      (one "hash = text" per line)
 *     zh-TW.txt
 *     de.txt
 *     fr.txt
 *     ...
 *
 * The name is ours alone: PR2.exe never references it, and it does not
 * collide with the game's own pr2_loca.cpr. There is no fallback to the
 * old "pr2locales" spelling -- rename the folder when upgrading.
 *
 * locale.ini format:
 *   language=zh
 *
 * The language can be overridden for a single launch without touching
 * this file: PR2Launcher.exe --lang=xx puts PR2_PACK_LANG=xx into the
 * child's environment, and that wins over the language= line. Launching
 * the game through PR2Launcher.exe with no argument leaves the variable
 * unset, so the language= line below still decides.
 *
 * NOTE: there is deliberately no width/line-length option here. The usable
 * line budget is a property of each on-screen control, not of the language:
 * the same string may fit in one tooltip and be dropped in a narrower box.
 * Break lines with <n> and verify per screen; do not encode a global limit.
 *
 * A hash that the pack does not cover is left untouched, so the engine's own
 * English stays on screen. That is the fallback -- no base-language file is
 * needed or supported.
 */
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

#include "pr2_locale.h"

/* ED_MAX: 每条译文的 UTF-16 单元数上限（不含结尾 '\0'）。
 * 实测全量 3548 条里最长的是 1061，有两倍余量。**不要下调**。
 * ED_LINES: 语言包条数上限。3548 条占 ED_LINES 的 21.6%，
 * 留了 4.6 倍余量给将来的语言。
 * LOC_MAX: 语言代码字节数（不含 '\0'）。"zh-TW" 这类代码远够用。 */
#define ED_MAX   2048
#define ED_LINES 16384
#define LOC_MAX  32

/* 【内存代价】txt[] 内联在结构里，每条 sizeof(Edit) = 4 KB+。
 * 3548 条 -> 约 14 MB 一次性驻留在游戏进程里。实测可接受，
 * 但若将来 ED_MAX 调大，这里会线性膨胀 —— 那时应改成
 * 「指针 + 单独分配」，而不是继续加大 ED_MAX。 */
typedef struct {
    unsigned hash;
    unsigned short txt[ED_MAX];
    int len;
} Edit;

static Edit* g_edits = NULL;
static int   g_editN = 0;

char  g_locale[LOC_MAX] = "";        /* active language code, e.g. zh */
char  g_locDir[MAX_PATH] = "";      /* full path of PR2Packs\ (no trailing backslash) */
static int g_envLang = 0;           /* 1 = language came from PR2_PACK_LANG */

/* ---------------- UTF-8 -> UTF-16 ---------------- */
static int Utf8ToWide(const char* in, unsigned short* out, int outMax) {
    int n = 0;
    const unsigned char* p = (const unsigned char*)in;
    while (*p && n < outMax - 1) {
        unsigned cp; int extra;
        if (*p < 0x80)                  { cp = *p++; extra = 0; }
        else if ((*p & 0xE0) == 0xC0)   { cp = *p & 0x1F; extra = 1; p++; }
        else if ((*p & 0xF0) == 0xE0)   { cp = *p & 0x0F; extra = 2; p++; }
        else if ((*p & 0xF8) == 0xF0)   { cp = *p & 0x07; extra = 3; p++; }
        else                             { cp = 0xFFFD; extra = 0; p++; }
        while (extra-- > 0) {
            if ((*p & 0xC0) != 0x80) { cp = 0xFFFD; break; }
            cp = (cp << 6) | (*p++ & 0x3F);
        }
        if (cp >= 0x10000) {
            cp -= 0x10000;
            if (n >= outMax - 2) break;
            out[n++] = (unsigned short)(0xD800 + (cp >> 10));
            out[n++] = (unsigned short)(0xDC00 + (cp & 0x3FF));
        } else {
            out[n++] = (unsigned short)cp;
        }
    }
    out[n] = 0;
    return n;
}

/* ---------------- override store ---------------- */
static Edit* FindEdit(unsigned h) {
    int i;
    for (i = 0; i < g_editN; i++)
        if (g_edits[i].hash == h) return &g_edits[i];
    return NULL;
}

/* 容量必须 >= g_editN + extra。AddEdit 只在 g_edits==NULL 时才扩容，
 * 所以调用方（LoadOverrideFile）必须**一次性**分配够整份文件的条数；
 * 若AddEdit 的实际调用次数超过预留，仍会越界写—— 这就是这里留
 * +1 余量的原因（行数统计与实际解析条数可能差1：末尾空行/BOM）。
 * 真要根治，应让 AddEdit 自己维护g_editCap 并按需扩容。 */
static int g_editCap = 0;

static Edit* GrowBy(int extra) {
    int   need = g_editN + extra + 1;      /* +1 余量，见上 */
    Edit* nb;
    if (need <= g_editCap) return g_edits;
    nb = (Edit*)HeapAlloc(GetProcessHeap(), 0, sizeof(Edit) * need);
    if (!nb) return NULL;
    if (g_editN && g_edits) memcpy(nb, g_edits, sizeof(Edit) * g_editN);
    if (g_edits) HeapFree(GetProcessHeap(), 0, g_edits);
    g_edits = nb;
    g_editCap = need;
    return nb;
}

static void AddEdit(unsigned h, const char* utf8) {
    if (g_editN >= ED_LINES) return;       /* 硬上限 */
    if (g_editN >= g_editCap && !GrowBy(1)) return;   /* 容量不足则放弃该条 */
    g_edits[g_editN].len  = Utf8ToWide(utf8, g_edits[g_editN].txt, ED_MAX);
    g_edits[g_editN].hash = h;
    g_editN++;
}

/* ---------------- parse "hash = text" file ---------------- */
static void LoadOverrideFile(const char* path) {
    HANDLE h;
    DWORD  sz, rd = 0;
    char*  buf;
    char*  p;
    char*  line;
    char*  t;
    int    lines = 0;

    h = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING,
                    FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) return;

    sz = GetFileSize(h, NULL);
    if (sz == 0 || sz > 16 * 1024 * 1024) { CloseHandle(h); return; }
    buf = (char*)HeapAlloc(GetProcessHeap(), 0, sz + 8);
    if (!buf) { CloseHandle(h); return; }
    if (!ReadFile(h, buf, sz, &rd, NULL)) {
        HeapFree(GetProcessHeap(), 0, buf); CloseHandle(h); return;
    }
    CloseHandle(h);
    buf[rd] = 0;

    p = buf;
    if (rd >= 3 && (unsigned char)buf[0] == 0xEF && (unsigned char)buf[1] == 0xBB
               && (unsigned char)buf[2] == 0xBF) p += 3;

    for (t = p; *t; t++) { if (*t == '\n') lines++; }
    lines++;
    if (!GrowBy(lines)) { HeapFree(GetProcessHeap(), 0, buf); return; }

    line = p;
    while (line && *line) {
        char* eol = strpbrk(line, "\r\n");
        char* s;
        unsigned long hv;
        if (eol) *eol = 0;
        s = line;
        while (*s == ' ' || *s == '\t') s++;
        if (*s && *s != '#' && *s != ';') {
            hv = strtoul(s, &s, 16);
            while (*s == ' ' || *s == '\t') s++;
            if (*s == '=' || *s == '\t') {
                s++;
                while (*s == ' ' || *s == '\t') s++;
                AddEdit((unsigned)hv, s);
            }
        }
        line = eol ? eol + 1 : NULL;
    }
    HeapFree(GetProcessHeap(), 0, buf);
}

/* 去首尾空白后复制（语言代码很短，够用）。 */
static void TrimCopy(char* dst, size_t cap, const char* src) {
    const char* p = src;
    while (*p == ' ' || *p == '\t') p++;
    const char* e = p + strlen(p);
    while (e > p && (e[-1] == ' ' || e[-1] == '\t' ||
                     e[-1] == '\r' || e[-1] == '\n')) e--;
    size_t n = (size_t)(e - p);
    if (n >= cap) n = cap ? cap - 1 : 0;
    if (n) memcpy(dst, p, n);
    if (cap) dst[n] = 0;
}

/* 读locale.ini 定语言，然后载入对应的语言包。
 *
 * 语言代码的优先级：
 *   1. 环境变量 PR2_PACK_LANG —— 由 PR2Launcher.exe 的 --lang=xx 传入，
 *      只影响这一次启动。GUI 用它来「这次用别的语言跑」，直接双击
 *      启动器时没有这个变量，行为与从前完全一致。
 *   2. PR2Packs\locale.ini 的 language= —— 默认语言，手工改它可持久切换。
 *   3. 下方 g_locale 的初始值 —— 连 locale.ini 都没有时的兜底。它必须与
 *      PR2Packs\ 下真实的语言包文件名一致，否则找不到包且没有任何提示，
 *      现象是游戏全程英文。
 *
 * 三级都不命中语言包时，包里没有的 hash 一律不动，引擎自带的英文原样
 * 显示，那才是兜底。
 * 诊断信息见 EditLoaded() / ActiveLocale() / ActivePackDir()。 */
void LoadEditFile(void) {
    char   exe[MAX_PATH];
    char*  q;
    char   fp[MAX_PATH];

    if (!GetModuleFileNameA(NULL, exe, MAX_PATH)) return;
    q = strrchr(exe, '\\');
    if (!q) return;
    *q = 0;

    lstrcpynA(g_locDir, exe, MAX_PATH);
    lstrcatA(g_locDir, "\\PR2Packs");

    /* Fallback when neither the env var nor locale.ini names a language.
     * This must name a file that really exists in PR2Packs\ -- an older
     * build defaulted to "zh-CN" while the pack ships as "zh.txt", so the
     * lookup failed silently and the whole localisation did nothing. */
    lstrcpynA(g_locale, "zh", LOC_MAX);

    /* 1. Per-launch override. The launcher passes it through the child's
     * environment (CreateProcessA is called with a NULL env block, which
     * means "inherit mine"), so this reaches us without any IPC.
     * Decided here and not further down, so an explicit per-launch choice
     * can never be undone by locale.ini. */
    {
        char  env[LOC_MAX] = "";
        DWORD n = GetEnvironmentVariableA("PR2_PACK_LANG", env,
                                          (DWORD)sizeof(env));
        if (n > 0 && n < LOC_MAX) {
            TrimCopy(g_locale, LOC_MAX, env);
            g_envLang = 1;
        }
    }

    /* 2. locale.ini -- only when step 1 did not decide. */
    if (!g_envLang) {
        char code[LOC_MAX];
        if (pr2_read_locale_language(exe, code, sizeof(code))) {
            TrimCopy(g_locale, LOC_MAX, code);
        }
    }

    /* the active language pack */
    lstrcpynA(fp, g_locDir, MAX_PATH);
    lstrcatA(fp, "\\");
    lstrcatA(fp, g_locale);
    lstrcatA(fp, ".txt");
    LoadOverrideFile(fp);
}

/* 供 pr2_text_source.cpp 调用：查该 hash 有没有译文。
 * 命中返回 UTF-16 缓冲与长度（长度单位是字符数），未命中返回 NULL，
 * 调用方据此让引擎保留自己的英文原文。
 *
 * ⚠ 查表为**线性扫描**，每次游戏取字都要走一遍；语言包满额时平均扫到一半。
 * ⚠ AddEdit 不做同 hash 去重：语言包内部若出现重复 hash，这里返回的是
 *   **先写入**的那条。要改成二分 + 去重，得同时改这两处。 */
unsigned short* OverrideEdit(unsigned h, unsigned* lenOut) {
    Edit* e = FindEdit(h);
    if (e && e->len > 0) { if (lenOut) *lenOut = (unsigned)e->len; return e->txt; }
    if (lenOut) *lenOut = 0;
    return NULL;
}

int         EditLoaded(void)          { return g_editN; }
const char* ActiveLocale(void)        { return g_locale; }
const char* ActivePackDir(void)       { return g_locDir; }
