// pr2_text_source.cpp -- 引擎取字的接管方（PR2TextSource.dll）
//
// 职责：接管引擎取字的三条路径，把 PR2Packs\<语言>.txt 里的译文送进去。
//   1. IAT hook CStringManager::Add —— 引擎注册主串表
//      (MISSION_NPC_GOODS_INFO) 时，replace_table() 整表重建成译文表。
//   2. vtable hook CW32StringManager::AddStringRes / LoadStringRes。
//   3. A2dLib::LoadStringRes 函数体 hook —— 兜住上两条没覆盖到的查询，
//      并把语言包里缺的 hash 连同引擎解析出的英文写进 PR2TextSource_gap.log。
//
// 不修改 PR2.exe：所有译文只由这个 DLL 提供。
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <psapi.h>

template<typename T> void* pmf_to_ptr(T pmf);  // fwd decl (defined near InstallHook)

struct Hook {                       // declared early so vtable hooks can reference it
    void MyAdd(const char* name, const void* data, unsigned int len);
    void MyAddStr(const char* name, const void* data, unsigned int len);
};

typedef void (__thiscall* AddFn)(void* pThis, const char* name, const void* data, unsigned int len);
static AddFn g_realAdd = NULL;       // original public CStringManager::Add (IAT)
static AddFn g_realAddStr = NULL;    // original CW32StringManager::AddStringRes (vtable)
static void* g_pMgr = NULL;          // captured CStringManager instance
static int g_fired = 0;
static const char* MAIN_TABLE = "MISSION_NPC_GOODS_INFO";

// ---- logging ----
static void log_line(const char* msg) {
    char path[MAX_PATH];
    if (GetModuleFileNameA(NULL, path, MAX_PATH)) {
        char* p = strrchr(path, '\\');
        if (p) strcpy(p + 1, "PR2TextSource.log");
    } else {
        strcpy(path, "C:\\PR2TextSource.log");
    }
    FILE* f = fopen(path, "a");
    if (f) { fprintf(f, "%s\n", msg); fclose(f); }
}

// ---- language pack (PR2Packs\ folder, multi-language) -------------------
// Defined in pr2_text_pack.c (pure C89) -> must be extern "C" to match linkage.
extern "C" {
unsigned short* OverrideEdit(unsigned hash, unsigned* lenOut);
int         EditLoaded(void);
void        LoadEditFile(void);
const char* ActiveLocale(void);
const char* ActivePackDir(void);
}

/* 查译文。命中返回 1 并填 outTxt/outLen（指向语言包内的 UTF-16 缓冲，
 * 长度单位是字符数）；未命中返回 0，调用方此时应让引擎用原文。
 * 数据来源见 pr2_text_pack.c 的 OverrideEdit。 */
static int FindOverride(unsigned hash, const unsigned short** outTxt, unsigned* outLen) {
    unsigned elen = 0;
    unsigned short* et = OverrideEdit(hash, &elen);
    if (et && elen > 0) { *outTxt = et; *outLen = elen; return 1; }
    return 0;
}


// ---- validate a decoded string-table blob ----
static int table_valid(const unsigned char* d, unsigned len) {
    if (len < 4) return 0;
    unsigned cnt = *(const unsigned*)d;
    if (cnt == 0 || cnt > 200000) return 0;
    unsigned totalWords = len / 2;
    unsigned poolStartWord = 2 + 8 * cnt;
    if (totalWords < poolStartWord) return 0;
    for (unsigned i = 0; i < cnt; i++) {
        unsigned e = 4 + 16 * i;
        unsigned off = *(const unsigned*)(d + e + 4);
        unsigned ln  = *(const unsigned*)(d + e + 12);
        if (4 + off + ln > len) return 0;
    }
    return 1;
}

// forward declarations (defined later, near write_wstr_inplace)

/* 整表替换：把引擎送来的原表重建为译文表。
 *
 * ★ 中文条目整条不显示的成因 ——与标签无关，是分词：
 *   引擎按**空格**切分单词。英文天然用空格分界，单词短、不易超宽；
 *   中文没有空格，整串汉字连同标点被当成**一个单词**去排版，
 *   超过该界面控件的可用宽度就整条丢弃 —— 不是截断，是不显示。
 *   每个控件能放多宽都不一样，没有通用值，只能逐条实测。
 *   对策是在合适位置加 <n> 手动断行，或改用更短的措辞。
 *   因此下面不做任何行宽估算或自动断行。
 *
 * 返回 HeapAlloc 的新表（交由引擎持有，我们不释放）；
 * 一条都替换不出时返回 NULL，调用方转而原样转发给引擎。
 * 返回 NULL 的另一个原因是输入不是有效的解码表（table_valid）。
 */
static unsigned char* replace_table(const unsigned char* d, unsigned len, unsigned* pnewlen) {
    if (!table_valid(d, len)) return NULL;
    unsigned cnt = *(const unsigned*)d;
    unsigned poolStartWord = 2 + 8 * cnt;
    unsigned outWords = poolStartWord, replaced = 0;
    for (unsigned i = 0; i < cnt; i++) {
        unsigned e = 4 + 16 * i;
        unsigned hash = *(const unsigned*)(d + e + 0);
        unsigned off  = *(const unsigned*)(d + e + 4);
        unsigned ln   = *(const unsigned*)(d + e + 12);
        const unsigned char* src = d + 4 + off;
        unsigned srclen = ln;
        const unsigned short* zh; unsigned zlen;
        if (FindOverride(hash, &zh, &zlen)) { srclen = zlen * 2; replaced++; }
        outWords += srclen / 2;
    }
    if (replaced == 0) return NULL;
    unsigned char* out = (unsigned char*)HeapAlloc(GetProcessHeap(), 0, outWords * 2);
    if (!out) return NULL;
    *(unsigned*)out = cnt;
    unsigned char* pp = out + poolStartWord * 2;
    unsigned curWord = poolStartWord;
    for (unsigned i = 0; i < cnt; i++) {
        unsigned e = 4 + 16 * i;
        unsigned hash  = *(const unsigned*)(d + e + 0);
        unsigned flags = *(const unsigned*)(d + e + 8);
        unsigned off   = *(const unsigned*)(d + e + 4);
        unsigned ln    = *(const unsigned*)(d + e + 12);
        const unsigned char* src = d + 4 + off;
        unsigned srclen = ln;
        const unsigned short* zh; unsigned zlen;
        if (FindOverride(hash, &zh, &zlen)) { src = (const unsigned char*)zh; srclen = zlen * 2; }
        unsigned offByte = 2 * curWord - 4;
        *(unsigned*)(out + e + 0) = hash;
        *(unsigned*)(out + e + 4) = offByte;
        *(unsigned*)(out + e + 8) = flags;
        *(unsigned*)(out + e + 12) = srclen;
        memcpy(pp, src, srclen);
        pp += srclen;
        curWord += srclen / 2;
    }
    *pnewlen = outWords * 2;
    return out;
}

// ============ LoadStringRes inline hook (diagnostic + capture) ============
// A2dLib-2.20A.dll resolves strings via LoadStringRes. We patch the REAL fn1 body
// (not the vtable) since we know its prologue. fn1:
//     bool __thiscall LoadStringRes(unsigned int hash, std::wstring& out)
//     prologue: 51 8B 41 10 53 (5 bytes)   // push ecx; mov eax,[ecx+10h]; push ebx
// 引擎的hash 查询全部经由 LoadStringRes（fn3 先把名字算成 hash 再调fn1），
// 所以只 hook fn1 就够。
// 除了在语言包命中时替换成译文，这里还把「包里没有、但引擎查得到」的 hash
// 连同引擎解析出的英文写进 PR2TextSource_gap.log，供补译。
// 可能出错的地方全部用 __try/__except 包住。

static BYTE* g_tramp1 = NULL;
static CRITICAL_SECTION g_lsrCS;
static int g_lsrCSInit = 0;
// ---- engine string hash (from A2dLib LoadStringRes(const char*)) ----
// h = 0; while(*s){ h = (h*0x71 + (signed char)*s) % 0x3B9AC9F7; s++; }
static unsigned EngineHash(const char* s) {
    if (!s) return 0;
    __int64 h = 0;
    while (*s) { h = (h * 0x71 + (signed char)*s) % 0x3B9AC9F7; s++; }
    return (unsigned)(unsigned __int64)h;
}

// read a 32-bit std::wstring (STLport or MSVC layout) into a caller buffer.
// Engine links STLport (stlport_vc745.dll): basic_string is typically
// { wchar_t* start, wchar_t* finish, wchar_t* end_of_storage }.  We probe both
// layouts, validate pointers, and wrap everything in SEH so capture can never crash.
static void read_wstr(const void* wsobj, wchar_t* buf, int buflen) {
    buf[0] = 0;
    if (!wsobj) return;
    __try {
        const unsigned* w = (const unsigned*)wsobj;
        // layout A (STLport): w[0]=start, w[1]=finish, w[2]=storage end
        if (w[0] > 0x10000u && w[1] >= w[0] && (w[1] - w[0]) < 0x8000u) {
            int n = (int)(w[1] - w[0]);
            if (n > buflen - 1) n = buflen - 1;
            memcpy(buf, (const void*)w[0], (size_t)n * 2);
            buf[n] = 0;
            return;
        }
        // layout B (MSVC): SSO buffer inline if size (at +16) <= 15
        unsigned sz = w[4];
        if (sz <= 15) {
            int n = 0;
            while (n < (int)sz && n < buflen - 1) { buf[n] = ((const wchar_t*)wsobj)[n]; n++; }
            buf[n] = 0;
            return;
        }
        // layout B (MSVC): heap pointer
        if (w[0] > 0x10000u && w[0] < 0x80000000u) {
            int n = (int)wcslen((const wchar_t*)w[0]);
            if (n > buflen - 1) n = buflen - 1;
            memcpy(buf, (const void*)w[0], (size_t)n * 2);
            buf[n] = 0;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {
        buf[0] = 0;
    }
}

// vtable hook：LoadStringRes / AddStringRes
// MyLsr 声明为非 static 的成员函数，让编译器按 __thiscall 生成 ECX 传参。
// slot 不写死：扫虚表找出与 A2dLib 导出函数地址相同的项再替换。
// 所有可能出错的操作都用 SEH 包住 —— 失手时最多该串显示为空，不会崩游戏。
static void* g_origLsr = NULL;
static int g_lsrVtHooked = 0;
static int g_strVtHooked = 0;

// Overwrite an STLport wstring's heap buffer in place with our text, only if it fits.
static void write_wstr_inplace(void* wsobj, const unsigned short* zh, unsigned zlen) {
    unsigned* w = (unsigned*)wsobj;
    if (w[0] < 0x10000u) return;           // not a heap buffer (SSO/empty) -> skip
    if (w[2] <= w[0]) return;
    unsigned cap = (w[2] - w[0]) / 2;      // capacity in chars
    if (zlen > cap) return;                // too long -> skip (no overflow)
    memcpy((void*)w[0], zh, zlen * 2);
    w[1] = w[0] + zlen * 2;                // advance finish pointer
}

// ABI (from disassembly): ECX=this, [esp+4]=hash, [esp+8]=out (wstring object).
// MyLsr must be a (non-static) member so it compiles as __thiscall; at runtime the
// engine passes the CStringManager instance in ECX, which we forward to the original.
struct LsrHook { bool __thiscall MyLsr(unsigned hash, void* out); };
static unsigned g_lsrLogN = 0;
static FILE* g_lsrF = NULL;
static void log_lsr_call(unsigned hash, int found, const wchar_t* w) {
    if (g_lsrLogN >= 5000) return;
    g_lsrLogN++;
    if (!g_lsrF) {
        char path[MAX_PATH];
        if (GetModuleFileNameA(NULL, path, MAX_PATH)) {
            char* p = strrchr(path, '\\'); if (p) strcpy(p + 1, "PR2TextSource_lsr.log");
        } else strcpy(path, "C:\\PR2TextSource_lsr.log");
        g_lsrF = fopen(path, "a");
    }
    if (!g_lsrF) return;
    char line[200];
    int pos = sprintf(line, "[LSR] 0x%08X f=%d ", hash, found);
    if (w && w[0]) {
        for (int i = 0; i < 6 && w[i]; i++) {
            if (w[i] < 0x80) line[pos++] = (char)w[i]; else { line[pos++] = '?'; }
        }
    }
    line[pos++] = '\n'; line[pos] = '\0';
    fputs(line, g_lsrF);
}
bool LsrHook::MyLsr(unsigned hash, void* out) {
    void* pThis = this;
    bool ret = false;
    if (g_origLsr) {
        __try {
            ret = ((bool(__thiscall*)(void*, unsigned, void*))g_origLsr)(pThis, hash, out);
        } __except (EXCEPTION_EXECUTE_HANDLER) { ret = false; }
    }
    const unsigned short* zh; unsigned zlen;
    int found = FindOverride(hash, &zh, &zlen);
    if (found) {
        // diagnostic: capture raw buffer header + whether overwrite applied
        const unsigned* w = (const unsigned*)out;
        unsigned cap = (w[0] >= 0x10000u && w[2] > w[0]) ? (w[2] - w[0]) / 2 : 0;
        int wrote = 0;
        unsigned short tmp[4096];
        unsigned n = zlen < 4096 ? zlen : 4096;
        if (n) memcpy(tmp, zh, n * 2);
        __try { write_wstr_inplace(out, tmp, n); wrote = 1; } __except (EXCEPTION_EXECUTE_HANDLER) {}
        if (!g_lsrF) {
            char path[MAX_PATH];
            if (GetModuleFileNameA(NULL, path, MAX_PATH)) {
                char* p = strrchr(path, '\\'); if (p) strcpy(p + 1, "PR2TextSource_lsr.log");
            } else strcpy(path, "C:\\PR2TextSource_lsr.log");
            g_lsrF = fopen(path, "a");
        }
        char dl[160];
        sprintf(dl, "[LSR*] 0x%08X raw=%08X,%08X,%08X zhlen=%u cap=%u %s\n",
                hash, w[0], w[1], w[2], n, cap,
                (wrote && n <= cap) ? "wrote" : (n > cap ? "SKIP(too-long)" : "skip"));
        if (g_lsrF) { fputs(dl, g_lsrF); fflush(g_lsrF); }
        log_lsr_call(hash, 1, NULL);
    } else {
        __try {
            wchar_t buf[600]; read_wstr(out, buf, 600);
            log_lsr_call(hash, 0, buf[0] ? buf : NULL);
        } __except (EXCEPTION_EXECUTE_HANDLER) { log_lsr_call(hash, 0, NULL); }
    }
    return ret;
}

// Scan the CStringManager vtable(s) for one exported virtual method and replace
// its slot with our detour. Used for both LoadStringRes (lookup) and AddStringRes
// (the per-script table loader the engine calls internally via vtable -- this is
// the path that delivers the menu/UI strings we were missing). SEH is not needed
// here (no derefs of untrusted data), but the swap is done under VirtualProtect.
static void HookVtableSlot(HMODULE h, const char* exportName, void* detour,
                           void** orig, int* doneFlag, const char* label) {
    if (*doneFlag) return;
    void* target = GetProcAddress(h, exportName);
    if (!target) { char b[96]; sprintf(b, "[text] %s: export not found", label); log_line(b); return; }
    BYTE* base = (BYTE*)h;
    void** candidates[2] = { NULL, NULL };
    int nc = 0;
    if (g_pMgr) candidates[nc++] = *(void***)g_pMgr;
    unsigned char* gp = base + 0x142084;     // g_pStringMgr singleton
    void* pm = *(void**)gp;
    if (pm && pm != g_pMgr) candidates[nc++] = *(void***)pm;
    for (int c = 0; c < nc; c++) {
        void** vt = candidates[c];
        if (!vt) continue;
        for (int i = 0; i < 512; i++) {
            if (vt[i] == target) {
                *orig = vt[i];
                DWORD old;
                if (VirtualProtect(&vt[i], sizeof(void*), PAGE_READWRITE, &old)) {
                    vt[i] = detour;
                    VirtualProtect(&vt[i], sizeof(void*), old, &old);
                    *doneFlag = 1;
                    char b[96]; sprintf(b, "[text] %s vtable hooked at slot %d (vt#%d)", label, i, c); log_line(b);
                }
                return;
            }
        }
    }
    char b[96]; sprintf(b, "[text] %s: 0x%p not found in %d vtable(s)", label, target, nc); log_line(b);
}

static void InstallVtableHooks(void) {
    HMODULE h = GetModuleHandleA("A2dLib-2.20A.dll");
    if (!h) return;
    HookVtableSlot(h,
        "?LoadStringRes@CW32StringManager@NA2dLib@@UAE_NIAAV?$basic_string@GV?$char_traits@G@_STL@@V?$allocator@G@2@@_STL@@@Z",
        pmf_to_ptr(&LsrHook::MyLsr), &g_origLsr, &g_lsrVtHooked, "LSR");
    HookVtableSlot(h,
        "?AddStringRes@CW32StringManager@NA2dLib@@MAE_NPBDPBXI@Z",
        pmf_to_ptr(&Hook::MyAddStr), (void**)&g_realAddStr, &g_strVtHooked, "AddStringRes");
}

// ================= Add hook (IAT) =================

struct Hook;

// Shared overlay for BOTH the public Add (IAT) and the internal AddStringRes
// (vtable). On the first call we install the vtable hooks (LoadStringRes +
// AddStringRes), then overlay the pack onto every table and log any record whose
// hash is absent from our map (the English source for later translation).
static void ApplyOverlay(AddFn real, const char* name, const void* data, unsigned len) {
    static int vtDone = 0;
    if (!vtDone) { vtDone = 1; InstallVtableHooks(); }

    /* 整表替换：把引擎送来的原表整体重建成译文表。
     * replace_table() 一条都替换不出时自己返回 NULL，此时走下面的原样转发。 */
    if (data && len >= 4) {
        unsigned int nlen = 0;
        unsigned char* nb = replace_table((const unsigned char*)data, len, &nlen);
        if (nb) {
            if (!g_fired) { g_fired = 1; log_line("[text] pack overlay applied to table"); }
            real(g_pMgr, name, nb, nlen);
            return;
        }
    }
    real(g_pMgr, name, data, len);
}

void Hook::MyAdd(const char* name, const void* data, unsigned int len) {
    if (!g_pMgr) g_pMgr = (void*)this;
    ApplyOverlay(g_realAdd, name, data, len);
}

void Hook::MyAddStr(const char* name, const void* data, unsigned int len) {
    if (!g_pMgr) g_pMgr = (void*)this;
    ApplyOverlay(g_realAddStr, name, data, len);
}

// ================= installers =================
static int PatchIATIn(HMODULE hMod, const char* dllName, const char* funcName, void* detour, void** original) {
    BYTE* base = (BYTE*)hMod;
    IMAGE_DOS_HEADER* dos = (IMAGE_DOS_HEADER*)base;
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) return 0;
    IMAGE_NT_HEADERS* nt = (IMAGE_NT_HEADERS*)(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) return 0;
    IMAGE_DATA_DIRECTORY* impdir = &nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (impdir->VirtualAddress == 0) return 0;
    IMAGE_IMPORT_DESCRIPTOR* imp = (IMAGE_IMPORT_DESCRIPTOR*)(base + impdir->VirtualAddress);
    int found = 0;
    for (; imp->Name; imp++) {
        const char* mod = (const char*)(base + imp->Name);
        if (_stricmp(mod, dllName) != 0) continue;
        IMAGE_THUNK_DATA* oft = (IMAGE_THUNK_DATA*)(base + imp->OriginalFirstThunk);
        IMAGE_THUNK_DATA* ft  = (IMAGE_THUNK_DATA*)(base + imp->FirstThunk);
        if (!ft) continue;
        for (; oft && oft->u1.AddressOfData; oft++, ft++) {
            if (IMAGE_SNAP_BY_ORDINAL(oft->u1.Ordinal)) continue;
            IMAGE_IMPORT_BY_NAME* ibn = (IMAGE_IMPORT_BY_NAME*)(base + oft->u1.AddressOfData);
            if (strcmp((const char*)ibn->Name, funcName) == 0) {
                if (!*original) *original = (void*)ft->u1.Function;
                DWORD old;
                if (VirtualProtect(&ft->u1.Function, sizeof(ULONG_PTR), PAGE_READWRITE, &old)) {
                    ft->u1.Function = (ULONG_PTR)detour;
                    VirtualProtect(&ft->u1.Function, sizeof(ULONG_PTR), old, &old);
                }
                found = 1;
            }
        }
    }
    return found;
}

template<typename T>
void* pmf_to_ptr(T pmf) { void* p; memcpy(&p, &pmf, sizeof(p)); return p; }

// ============ CScreenStrings::ResolveByHash hook ============
// A2dLib thunk @0x1DC5 -> real body @0x25C70.
//   bool __thiscall ResolveByHash(int hashKey, std::wstring& out)
// Binary-searches CScreenStrings' internal hash-sorted array and assigns the
// resolved text into `out`. This is the path that serves the menu / UI /
// exit-confirm strings that were rendering blank (they never reach LoadStringRes).
// We translate in place when the hash is in our pack; otherwise, if the
// engine DID resolve English text, we log it as a gap to translate later.
// Everything is SEH-wrapped: at worst a string stays blank, never a crash.
static void* g_resolveReal = NULL;
static int g_resolveHooked = 0;
static unsigned g_resolveN = 0, g_resolveZhN = 0;
static FILE* g_resolveF = NULL;
static unsigned g_resolveGapSet[2048];
static int g_resolveGapN = 0;

static void resolve_log_open(void) {
    if (g_resolveF) return;
    char path[MAX_PATH];
    if (GetModuleFileNameA(NULL, path, MAX_PATH)) {
        char* p = strrchr(path, '\\');
        if (p) strcpy(p + 1, "PR2TextSource_resolve.log");
    } else strcpy(path, "C:\\PR2TextSource_resolve.log");
    g_resolveF = fopen(path, "w");
    if (g_resolveF) fputs("=== CScreenStrings::ResolveByHash (menu/UI) gaps ===\n", g_resolveF);
}

static void log_resolve_full(unsigned hash, void* out, bool ret) {
    // full diagnostic: every ResolveByHash call -> raw wstring header + decoded text
    if (!g_resolveF) resolve_log_open();
    if (!g_resolveF) return;
    if (g_resolveN >= 8000) return;   // cap
    const unsigned* w = (const unsigned*)out;
    unsigned p0 = w[0], p1 = w[1], p2 = w[2];
    wchar_t buf[600]; read_wstr(out, buf, 600);
    char line[1600];
    int pos = sprintf(line, "[R] 0x%08X ret=%d raw=%08X,%08X,%08X txt=",
                      hash, ret ? 1 : 0, p0, p1, p2);
    for (int i = 0; buf[i] && pos < 1580; i++) {
        unsigned short c = buf[i];
        if (c < 0x80) line[pos++] = (char)c;
        else if (c < 0x800) { line[pos++] = (char)(0xC0 | (c >> 6)); line[pos++] = (char)(0x80 | (c & 0x3F)); }
        else { line[pos++] = (char)(0xE0 | (c >> 12)); line[pos++] = (char)(0x80 | ((c >> 6) & 0x3F)); line[pos++] = (char)(0x80 | (c & 0x3F)); }
    }
    line[pos++] = '\n'; line[pos] = '\0';
    fputs(line, g_resolveF); fflush(g_resolveF);
}

static void log_resolve_gap(unsigned hash, void* out) {
    for (int i = 0; i < g_resolveGapN; i++) if (g_resolveGapSet[i] == hash) return;
    if (g_resolveGapN >= 2048) return;
    g_resolveGapSet[g_resolveGapN++] = hash;
    if (!g_resolveF) resolve_log_open();
    if (!g_resolveF) return;
    wchar_t buf[600]; read_wstr(out, buf, 600);
    char line[1400];
    int pos = sprintf(line, "[RGAP] 0x%08X  ", hash);
    for (int i = 0; buf[i] && pos < 1380; i++) {
        unsigned short c = buf[i];
        if (c < 0x80) line[pos++] = (char)c;
        else if (c < 0x800) { line[pos++] = (char)(0xC0 | (c >> 6)); line[pos++] = (char)(0x80 | (c & 0x3F)); }
        else { line[pos++] = (char)(0xE0 | (c >> 12)); line[pos++] = (char)(0x80 | ((c >> 6) & 0x3F)); line[pos++] = (char)(0x80 | (c & 0x3F)); }
    }
    line[pos++] = '\n'; line[pos] = '\0';
    fputs(line, g_resolveF); fflush(g_resolveF);
}

struct ResolveHook { bool __thiscall MyResolve(int key, void* out); };
bool ResolveHook::MyResolve(int key, void* out) {
    bool ret = false;
    __try {
        int r = 0;
        void* pThis = (void*)this;
        void* real = g_resolveReal;
        void* o = out;
        int k = key;
        // 照引擎自己的调用序列执行真实的 ResolveByHash 函数体：
        //   ECX = this ; push out ; push key ; call body
        // 直接调函数体，不需要 trampoline，栈也不会错位。
        __asm {
            mov ecx, pThis
            push o
            push k
            call real
            mov r, eax
        }
        ret = (r != 0);
    } __except (EXCEPTION_EXECUTE_HANDLER) { ret = false; }
    g_resolveN++;
    __try { log_resolve_full((unsigned)key, out, ret); } __except (EXCEPTION_EXECUTE_HANDLER) {}
    const unsigned short* zh; unsigned zlen;
    if (FindOverride((unsigned)key, &zh, &zlen)) {
        g_resolveZhN++;
        unsigned short tmp[4096];
        unsigned n = zlen < 4096 ? zlen : 4096;
        if (n) memcpy(tmp, zh, n * 2);
        __try { write_wstr_inplace(out, tmp, n); } __except (EXCEPTION_EXECUTE_HANDLER) {}
    } else if (ret) {
        __try { log_resolve_gap((unsigned)key, out); } __except (EXCEPTION_EXECUTE_HANDLER) {}
    }
    return ret;
}

static void InstallResolveHook(void) {
    if (g_resolveHooked) return;
    HMODULE h = GetModuleHandleA("A2dLib-2.20A.dll");
    if (!h) { log_line("[text] ResolveHook: A2dLib-2.20A.dll not loaded yet"); return; }
    g_resolveReal = (BYTE*)h + 0x25C70;   // real ResolveByHash body
    BYTE* thunk = (BYTE*)h + 0x1DC5;      // jmp 0x10025C70 (the callers' entry)
    void* detour = pmf_to_ptr(&ResolveHook::MyResolve);
    DWORD old;
    if (VirtualProtect(thunk, 5, PAGE_EXECUTE_READWRITE, &old)) {
        long rel = (long)((BYTE*)detour - (thunk + 5));
        thunk[0] = 0xE9;
        *(long*)(thunk + 1) = rel;
        VirtualProtect(thunk, 5, old, &old);
        g_resolveHooked = 1;
        log_line("[text] ResolveHook: CScreenStrings::ResolveByHash patched (thunk 0x1DC5 -> MyResolve)");
    } else {
        log_line("[text] ResolveHook: VirtualProtect failed");
    }
}

static void InstallHook(void) {
    if (g_realAdd) return;
    LoadEditFile();                              // PR2Packs\ language pack
    if (EditLoaded()) {
        char b[160];
        sprintf(b, "[text] pack '%s' from %s: %d overrides", ActiveLocale(), ActivePackDir(), EditLoaded());
        log_line(b);
    } else {
        /* 没有加载到任何条目 = 游戏会全程显示英文。这是个静默失败：
         * 屏幕上看不出是「没汉化」还是「汉化坏了」。把语言代码和目录
         * 都写出来，才能判断是语言名写错、包没装，还是文件损坏。 */
        char b[320];
        sprintf(b, "[text] NO pack loaded: language '%s' from %s "
                   "(pack file missing or empty -- the game will show "
                   "the original English)",
                ActiveLocale(), ActivePackDir());
        log_line(b);
    }
    void* detour = pmf_to_ptr(&Hook::MyAdd);
    const char* ADD = "?Add@CStringManager@NA2dLib@@QAEXPBDPBXI@Z";
    int n = 0;
    // The game EXE itself
    if (PatchIATIn(GetModuleHandleA(NULL), "A2dLib-2.20A.dll", ADD, detour, (void**)&g_realAdd)) n++;
    // Every other module in the process (Walhalla, WalExtPR2, lua, ...). A2dLib
    // defines Add itself (calls via thiscall), so skip it.
    HMODULE mods[256]; DWORD cb = 0;
    if (EnumProcessModules(GetCurrentProcess(), mods, sizeof(mods), &cb)) {
        DWORD nm = cb / sizeof(HMODULE);
        if (nm > 256) nm = 256;
        for (DWORD k = 0; k < nm; k++) {
            if (mods[k] == GetModuleHandleA(NULL)) continue;
            char mname[MAX_PATH];
            if (GetModuleBaseNameA(GetCurrentProcess(), mods[k], mname, MAX_PATH)) {
                if (_stricmp(mname, "A2dLib-2.20A.dll") == 0) continue;
                if (PatchIATIn(mods[k], "A2dLib-2.20A.dll", ADD, detour, (void**)&g_realAdd)) {
                    char b[160]; sprintf(b, "[text] Add IAT patched in %s", mname); log_line(b);
                    n++;
                }
            }
        }
    }
    InstallResolveHook();
    if (n > 0) log_line("[text] hook installed (CStringManager::Add -> MyAdd)");
    else log_line("[text] FAILED: Add not found in any module IAT");
}

BOOL WINAPI DllMain(HINSTANCE hinst, DWORD reason, LPVOID reserved) {
    (void)hinst; (void)reserved;
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hinst);
        InstallHook();
    }
    return TRUE;
}
