/* pr2_launcher_gui.cpp -- 带界面的语言选择启动器。
 *
 * 界面字符串来自 lang/gui.<ui>.ini（UTF-8）；找不到时回退 en，再回退内置英文。
 * 不重新实现注入：只调用同目录的 PR2Launcher.exe --lang=<代码>。
 */
#include <windows.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

#define ID_LANG    1001
#define ID_LAUNCH  1002
#define ID_VANILLA 1003
#define ID_REFRESH 1004
#define ID_STATUS  1005

static char g_root[MAX_PATH];
static char g_codes[64][64];
static int  g_codeCount = 0;
static char g_packAlias[64][256];
static char g_packGui[64][16];
static char g_defaultUi[16] = "en";
static HWND g_combo = NULL;
static HWND g_status = NULL;
static HWND g_label = NULL;
static HWND g_btnLaunch = NULL;
static HWND g_btnVanilla = NULL;
static HWND g_btnRefresh = NULL;
static HWND g_hwnd = NULL;

/* ---- UTF-8 -> wide（只用于立即传给 Win32） ---- */
static const wchar_t* W(const char* s) {
    static wchar_t bufs[8][1024];
    static int idx = 0;
    wchar_t* b = bufs[idx++ % 8];
    MultiByteToWideChar(CP_UTF8, 0, s, -1, b, 1023);
    b[1023] = 0;
    return b;
}

/* ---- 极简 key=value 语言文件 ---- */
#define MAX_STR 96
static char g_keys[MAX_STR][64];
static char g_vals[MAX_STR][1024];
static int  g_strCount = 0;

static const char* BUILTIN[][2] = {
    {"title", "Port Royale 2 Launcher"},
    {"label.language", "Language pack:"},
    {"button.launch", "Launch localized"},
    {"button.vanilla", "Launch original"},
    {"button.refresh", "Refresh"},
    {"status.count", "%d language pack(s)"},
    {"status.none", "No .txt in PR2Packs"},
    {"status.launched", "Localized game launched."},
    {"status.vanilla", "Original game launched."},
    {"error.no_launcher", "PR2Launcher.exe not found in this folder."},
    {"error.no_language", "No language pack selected."},
    {"error.launch_failed", "Failed to start PR2Launcher.exe."},
    {"error.exit_code", "Launcher exit code %lu; the game did not start."},
    {"error.font_missing", "fonts\\%s\\ has no TTF fonts."},
    {NULL, NULL}
};

static void Trim(char* s) {
    char* p = s;
    while (*p == ' ' || *p == '\t') p++;
    if (p != s) memmove(s, p, strlen(p) + 1);
    size_t n = strlen(s);
    while (n && (s[n-1] == '\r' || s[n-1] == '\n' || s[n-1] == ' ' || s[n-1] == '\t')) {
        s[--n] = 0;
    }
}

static void Unescape(char* s) {
    char* w = s;
    for (char* p = s; *p; p++) {
        if (p[0] == '\\' && p[1] == 'n') { *w++ = '\n'; p++; }
        else *w++ = *p;
    }
    *w = 0;
}

static int LoadIni(const char* path) {
    FILE* f = fopen(path, "rb");
    if (!f) return 0;
    char line[1200];
    int loaded = 0;
    if (fgets(line, sizeof(line), f)) {
        unsigned char* u = (unsigned char*)line;
        if (u[0] == 0xEF && u[1] == 0xBB && u[2] == 0xBF) {
            memmove(line, line + 3, strlen(line + 3) + 1);
        } else {
            rewind(f);
        }
    } else {
        fclose(f);
        return 0;
    }
    while (fgets(line, sizeof(line), f)) {
        char* p = line;
        Trim(p);
        if (!*p || *p == '#' || *p == ';' || *p == '[') continue;
        char* eq = strchr(p, '=');
        if (!eq) continue;
        *eq = 0;
        char* key = p; Trim(key);
        char* val = eq + 1; Trim(val);
        if (!*key || g_strCount >= MAX_STR) continue;
        strncpy(g_keys[g_strCount], key, 63);
        g_keys[g_strCount][63] = 0;
        strncpy(g_vals[g_strCount], val, 1023);
        g_vals[g_strCount][1023] = 0;
        Unescape(g_vals[g_strCount]);
        g_strCount++;
        loaded++;
    }
    fclose(f);
    return loaded;
}

static const char* T8(const char* key) {
    for (int i = 0; i < g_strCount; i++) {
        if (strcmp(g_keys[i], key) == 0) return g_vals[i];
    }
    for (int i = 0; BUILTIN[i][0]; i++) {
        if (strcmp(BUILTIN[i][0], key) == 0) return BUILTIN[i][1];
    }
    return key;
}

static const wchar_t* T(const char* key) { return W(T8(key)); }

static const wchar_t* TF(const char* key, ...) {
    char buf[1600];
    va_list ap;
    va_start(ap, key);
    vsnprintf(buf, sizeof(buf), T8(key), ap);
    va_end(ap);
    return W(buf);
}

static void SaveIniValue(const char* path, const char* key, const char* value) {
    char tmp[MAX_PATH], line[1024];
    snprintf(tmp, sizeof(tmp), "%s.tmp", path);
    int klen = (int)strlen(key);
    int replaced = 0;
    FILE* in = fopen(path, "rb");
    FILE* out = fopen(tmp, "wb");
    if (!out) { if (in) fclose(in); return; }
    if (in) {
        while (fgets(line, sizeof(line), in)) {
            char probe[1024];
            strncpy(probe, line, sizeof(probe) - 1);
            probe[sizeof(probe) - 1] = 0;
            Trim(probe);
            if (strncmp(probe, key, klen) == 0) {
                char* p = probe + klen;
                while (*p == ' ' || *p == '\t') p++;
                if (*p == '=') {
                    fprintf(out, "%s=%s\n", key, value);
                    replaced = 1;
                    continue;
                }
            }
            fputs(line, out);
        }
        fclose(in);
    }
    if (!replaced) fprintf(out, "%s=%s\n", key, value);
    fclose(out);
    if (!MoveFileExA(tmp, path, MOVEFILE_REPLACE_EXISTING)) remove(tmp);
}

static void SaveLocaleLanguage(const char* lang) {
    char path[MAX_PATH];
    snprintf(path, sizeof(path), "%s\\PR2Packs\\locale.ini", g_root);
    SaveIniValue(path, "language", lang);
}

static void LoadGuiStringsFor(const char* ui) {
    g_strCount = 0;
    char path[MAX_PATH];
    snprintf(path, sizeof(path), "%s\\lang\\gui.%s.ini", g_root, ui);
    LoadIni(path);
    if (!g_strCount && _stricmp(ui, "en") != 0) {
        snprintf(path, sizeof(path), "%s\\lang\\gui.en.ini", g_root);
        LoadIni(path);
    }
}

static void LoadGuiStrings(void) {
    char ui[16];
    LANGID id = GetUserDefaultUILanguage();
    switch (PRIMARYLANGID(id)) {
    case LANG_CHINESE: strcpy(ui, "zh"); break;
    case LANG_JAPANESE: strcpy(ui, "ja"); break;
    default: strcpy(ui, "en"); break;
    }
    strncpy(g_defaultUi, ui, sizeof(g_defaultUi) - 1);
    g_defaultUi[sizeof(g_defaultUi) - 1] = 0;
    LoadGuiStringsFor(g_defaultUi);
}

static void ReadPackMeta(const char* path, char* alias, int acap,
                         char* gui, int gcap) {
    alias[0] = 0;
    gui[0] = 0;
    FILE* f = fopen(path, "rb");
    if (!f) return;
    char line[1024];
    for (int n = 0; n < 64 && fgets(line, sizeof(line), f); n++) {
        char* p = line;
        Trim(p);
        if (!*p || *p == ';') continue;
        if (strncmp(p, "# pack-meta ", 12) != 0) {
            if (*p == '#') continue;
            break;              /* 第一条 hash = text 之后不再读 */
        }
        p += 12;
        char* eq = strchr(p, '=');
        if (!eq) continue;
        *eq = 0;
        char* key = p; Trim(key);
        char* val = eq + 1; Trim(val);
        if (strcmp(key, "alias") == 0) {
            strncpy(alias, val, acap - 1);
            alias[acap - 1] = 0;
        } else if (strcmp(key, "gui") == 0) {
            strncpy(gui, val, gcap - 1);
            gui[gcap - 1] = 0;
        }
    }
    fclose(f);
}

static void UpdateStatus(void) {
    if (!g_status) return;
    SetWindowTextW(g_status, g_codeCount ? TF("status.count", g_codeCount)
                                         : T("status.none"));
}

static void UpdateTexts(void) {
    if (!g_hwnd) return;
    SetWindowTextW(g_hwnd, T("title"));
    if (g_label) SetWindowTextW(g_label, T("label.language"));
    if (g_btnLaunch) SetWindowTextW(g_btnLaunch, T("button.launch"));
    if (g_btnVanilla) SetWindowTextW(g_btnVanilla, T("button.vanilla"));
    if (g_btnRefresh) SetWindowTextW(g_btnRefresh, T("button.refresh"));
    UpdateStatus();
}

static void ApplyPackLanguage(void) {
    int sel = (int)SendMessageW(g_combo, CB_GETCURSEL, 0, 0);
    const char* ui = g_defaultUi;
    if (sel >= 0 && sel < g_codeCount && g_packGui[sel][0]) ui = g_packGui[sel];
    LoadGuiStringsFor(ui);
    UpdateTexts();
}

static void DirOf(const char* path, char* out) {
    strcpy(out, path);
    char* p = strrchr(out, '\\');
    if (p) *p = '\0';
    else strcpy(out, ".");
}

static int ReadLocale(char* out, int cap) {
    char path[MAX_PATH], line[512];
    snprintf(path, sizeof(path), "%s\\PR2Packs\\locale.ini", g_root);
    FILE* f = fopen(path, "rb");
    if (!f) return 0;
    int found = 0;
    while (fgets(line, sizeof(line), f)) {
        char* p = line;
        while (*p == ' ' || *p == '\t') p++;
        if (strncmp(p, "language", 8) != 0) continue;
        p += 8;
        while (*p == ' ' || *p == '\t') p++;
        if (*p != '=') continue;
        p++;
        while (*p == ' ' || *p == '\t') p++;
        char* e = p;
        while (*e && *e != '\r' && *e != '\n' && *e != ' ' && *e != '\t') e++;
        *e = '\0';
        if (*p) { strncpy(out, p, cap - 1); out[cap - 1] = '\0'; found = 1; }
        break;
    }
    fclose(f);
    return found;
}

static int HasLanguageFonts(const char* lang) {
    static const char* names[4] = {
        "ARIAL.TTF", "ELGRECO_.TTF", "Tiepolo_black.ttf", "Tiepolo_bold.ttf"
    };
    for (int i = 0; i < 4; i++) {
        char p[MAX_PATH];
        snprintf(p, sizeof(p), "%s\\fonts\\%s\\%s", g_root, lang, names[i]);
        if (GetFileAttributesA(p) == INVALID_FILE_ATTRIBUTES) return 0;
    }
    return 1;
}

static void LoadLanguages(void) {
    char pattern[MAX_PATH], current[64];
    g_codeCount = 0;
    memset(g_packAlias, 0, sizeof(g_packAlias));
    memset(g_packGui, 0, sizeof(g_packGui));
    SendMessageW(g_combo, CB_RESETCONTENT, 0, 0);
    snprintf(pattern, sizeof(pattern), "%s\\PR2Packs\\*.txt", g_root);
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA(pattern, &fd);
    if (h != INVALID_HANDLE_VALUE) {
        do {
            if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) continue;
            char* dot = strrchr(fd.cFileName, '.');
            if (!dot || _stricmp(dot, ".txt") != 0) continue;
            if (g_codeCount >= 64) break;
            int n = (int)(dot - fd.cFileName);
            if (n <= 0 || n >= 64) continue;
            strncpy(g_codes[g_codeCount], fd.cFileName, n);
            g_codes[g_codeCount][n] = '\0';
            char full[MAX_PATH];
            snprintf(full, sizeof(full), "%s\\PR2Packs\\%s",
                     g_root, fd.cFileName);
            ReadPackMeta(full, g_packAlias[g_codeCount], 256,
                         g_packGui[g_codeCount], 16);
            const char* label = g_packAlias[g_codeCount][0]
                              ? g_packAlias[g_codeCount]
                              : g_codes[g_codeCount];
            SendMessageW(g_combo, CB_ADDSTRING, 0, (LPARAM)W(label));
            g_codeCount++;
        } while (FindNextFileA(h, &fd));
        FindClose(h);
    }

    int sel = 0;
    if (ReadLocale(current, sizeof(current))) {
        for (int i = 0; i < g_codeCount; i++) {
            if (_stricmp(g_codes[i], current) == 0) { sel = i; break; }
        }
    }
    if (g_codeCount) SendMessageW(g_combo, CB_SETCURSEL, sel, 0);
    ApplyPackLanguage();
}

static void Launch(const char* lang, int vanilla) {
    char launcher[MAX_PATH], cmd[1024];
    snprintf(launcher, sizeof(launcher), "%s\\PR2Launcher.exe", g_root);
    if (GetFileAttributesA(launcher) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, T("error.no_launcher"), T("title"), MB_ICONERROR);
        return;
    }
    if (!vanilla) {
        if (!lang || !*lang) {
            MessageBoxW(NULL, T("error.no_language"), T("title"), MB_ICONWARNING);
            return;
        }
        if (!HasLanguageFonts(lang)) {
            if (MessageBoxW(NULL, TF("error.font_missing", lang), T("title"),
                            MB_YESNO | MB_ICONWARNING) != IDYES) {
                return;
            }
        }
        snprintf(cmd, sizeof(cmd), "\"%s\" --lang=%s", launcher, lang);
    } else {
        snprintf(cmd, sizeof(cmd), "\"%s\" --vanilla", launcher);
    }
    STARTUPINFOA si = {0}; si.cb = sizeof(si);
    PROCESS_INFORMATION pi = {0};
    if (!CreateProcessA(NULL, cmd, NULL, NULL, FALSE, CREATE_NO_WINDOW,
                        NULL, g_root, &si, &pi)) {
        MessageBoxW(NULL, T("error.launch_failed"), T("title"), MB_ICONERROR);
        return;
    }
    DWORD code = 0;
    if (WaitForSingleObject(pi.hProcess, 4000) == WAIT_OBJECT_0) {
        GetExitCodeProcess(pi.hProcess, &code);
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    if (code != 0) {
        MessageBoxW(NULL, TF("error.exit_code", code), T("title"), MB_ICONERROR);
    } else {
        if (!vanilla && lang && *lang) SaveLocaleLanguage(lang);
        SetWindowTextW(g_status, vanilla ? T("status.vanilla") : T("status.launched"));
    }
}

static LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_CREATE: {
        g_hwnd = hwnd;
        g_label = CreateWindowW(L"STATIC", T("label.language"), WS_CHILD | WS_VISIBLE,
                      16, 18, 420, 20, hwnd, NULL, NULL, NULL);
        g_combo = CreateWindowW(L"COMBOBOX", NULL,
                                WS_CHILD | WS_VISIBLE | WS_TABSTOP |
                                CBS_DROPDOWNLIST | WS_VSCROLL,
                                16, 42, 420, 200, hwnd, (HMENU)ID_LANG,
                                NULL, NULL);
        g_btnLaunch = CreateWindowW(L"BUTTON", T("button.launch"),
                      WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON,
                      16, 84, 190, 32, hwnd, (HMENU)ID_LAUNCH, NULL, NULL);
        g_btnVanilla = CreateWindowW(L"BUTTON", T("button.vanilla"),
                      WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON,
                      216, 84, 150, 32, hwnd, (HMENU)ID_VANILLA, NULL, NULL);
        g_btnRefresh = CreateWindowW(L"BUTTON", T("button.refresh"),
                      WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON,
                      376, 84, 80, 32, hwnd, (HMENU)ID_REFRESH, NULL, NULL);
        g_status = CreateWindowW(L"STATIC", L"",
                                 WS_CHILD | WS_VISIBLE | SS_LEFT,
                                 16, 126, 440, 40, hwnd, (HMENU)ID_STATUS,
                                 NULL, NULL);
        LoadLanguages();
        return 0;
    }
    case WM_COMMAND:
        switch (LOWORD(wp)) {
        case ID_LANG:
            if (HIWORD(wp) == CBN_SELCHANGE) ApplyPackLanguage();
            break;
        case ID_LAUNCH: {
            int sel = (int)SendMessageW(g_combo, CB_GETCURSEL, 0, 0);
            if (sel >= 0 && sel < g_codeCount) Launch(g_codes[sel], 0);
            break;
        }
        case ID_VANILLA:
            Launch(NULL, 1);
            break;
        case ID_REFRESH:
            LoadLanguages();
            break;
        }
        return 0;
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPSTR cmd, int show) {
    (void)prev; (void)cmd;
    GetModuleFileNameA(NULL, g_root, MAX_PATH);
    DirOf(g_root, g_root);
    LoadGuiStrings();

    WNDCLASSW wc = {0};
    wc.lpfnWndProc = WndProc;
    wc.hInstance = inst;
    wc.lpszClassName = L"PR2LauncherGUI";
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1);
    RegisterClassW(&wc);

    HWND hwnd = CreateWindowW(L"PR2LauncherGUI", T("title"),
                              WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU |
                              WS_MINIMIZEBOX,
                              CW_USEDEFAULT, CW_USEDEFAULT, 490, 210,
                              NULL, NULL, inst, NULL);
    ShowWindow(hwnd, show);
    UpdateWindow(hwnd);

    MSG msg;
    while (GetMessage(&msg, NULL, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessage(&msg);
    }
    return 0;
}
