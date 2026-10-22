/* pr2_launcher_gui.cpp -- 带界面的语言选择启动器。
 *
 * 不重新实现注入：只调用同目录的 PR2Launcher.exe --lang=<代码>。
 * 语言列表来自 PR2Packs\*.txt，默认选中 locale.ini 的 language=。
 */
#include <windows.h>
#include <stdio.h>
#include <string.h>

#define ID_LANG   1001
#define ID_LAUNCH 1002
#define ID_VANILLA 1003
#define ID_REFRESH 1004
#define ID_STATUS 1005

static char g_root[MAX_PATH];
static char g_codes[64][64];
static int  g_codeCount = 0;
static HWND g_combo = NULL;
static HWND g_status = NULL;

/* UTF-8 源字符串 -> 宽字符；只用于立即传给 Win32。 */
static const wchar_t* W(const char* s) {
    static wchar_t bufs[8][512];
    static int idx = 0;
    wchar_t* b = bufs[idx++ % 8];
    MultiByteToWideChar(CP_UTF8, 0, s, -1, b, 511);
    b[511] = 0;
    return b;
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

static void LoadLanguages(void) {
    char pattern[MAX_PATH], current[64];
    g_codeCount = 0;
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
            char label[128];
            snprintf(label, sizeof(label), "%s", g_codes[g_codeCount]);
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
    char msg[256];
    snprintf(msg, sizeof(msg), "%d 个语言包", g_codeCount);
    if (!g_codeCount) strncat(msg, "（PR2Packs 里没有 .txt）", sizeof(msg) - strlen(msg) - 1);
    SetWindowTextW(g_status, W(msg));
}

static void Launch(const char* lang, int vanilla) {
    char launcher[MAX_PATH], cmd[1024];
    snprintf(launcher, sizeof(launcher), "%s\\PR2Launcher.exe", g_root);
    if (GetFileAttributesA(launcher) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, W("同目录下找不到 PR2Launcher.exe。"), W("PR2 启动器"), MB_ICONERROR);
        return;
    }
    if (vanilla) {
        snprintf(cmd, sizeof(cmd), "\"%s\" --vanilla", launcher);
    } else {
        if (!lang || !*lang) {
            MessageBoxW(NULL, W("还没有选择语言包。"), W("PR2 启动器"), MB_ICONWARNING);
            return;
        }
        snprintf(cmd, sizeof(cmd), "\"%s\" --lang=%s", launcher, lang);
    }
    STARTUPINFOA si = {0}; si.cb = sizeof(si);
    PROCESS_INFORMATION pi = {0};
    if (!CreateProcessA(NULL, cmd, NULL, NULL, FALSE, CREATE_NO_WINDOW,
                        NULL, g_root, &si, &pi)) {
        MessageBoxW(NULL, W("启动 PR2Launcher.exe 失败。"), W("PR2 启动器"), MB_ICONERROR);
        return;
    }
    DWORD code = 0;
    if (WaitForSingleObject(pi.hProcess, 4000) == WAIT_OBJECT_0) {
        GetExitCodeProcess(pi.hProcess, &code);
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    if (code != 0) {
        char msg[256];
        snprintf(msg, sizeof(msg),
                 "启动器退出码 %lu，游戏没有启动。\n"
                 "检查 PR2Launcher.exe / PR2TextSource.dll 是否在同目录。", code);
        MessageBoxW(NULL, W(msg), W("PR2 启动器"), MB_ICONERROR);
    } else {
        SetWindowTextW(g_status, W(vanilla ? "已启动原版游戏。" : "已启动本地化游戏。"));
    }
}

static LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    switch (msg) {
    case WM_CREATE: {
        CreateWindowW(L"STATIC", W("语言包："), WS_CHILD | WS_VISIBLE,
                      16, 18, 320, 20, hwnd, NULL, NULL, NULL);
        g_combo = CreateWindowW(L"COMBOBOX", NULL,
                                WS_CHILD | WS_VISIBLE | WS_TABSTOP |
                                CBS_DROPDOWNLIST | WS_VSCROLL,
                                16, 42, 320, 200, hwnd, (HMENU)ID_LANG,
                                NULL, NULL);
        CreateWindowW(L"BUTTON", W("启动本地化"),
                      WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON,
                      16, 84, 130, 32, hwnd, (HMENU)ID_LAUNCH, NULL, NULL);
        CreateWindowW(L"BUTTON", W("启动原版"),
                      WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON,
                      156, 84, 100, 32, hwnd, (HMENU)ID_VANILLA, NULL, NULL);
        CreateWindowW(L"BUTTON", W("刷新"),
                      WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON,
                      266, 84, 70, 32, hwnd, (HMENU)ID_REFRESH, NULL, NULL);
        g_status = CreateWindowW(L"STATIC", L"",
                                 WS_CHILD | WS_VISIBLE | SS_LEFT,
                                 16, 126, 320, 40, hwnd, (HMENU)ID_STATUS,
                                 NULL, NULL);
        LoadLanguages();
        return 0;
    }
    case WM_COMMAND:
        switch (LOWORD(wp)) {
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

    WNDCLASSW wc = {0};
    wc.lpfnWndProc = WndProc;
    wc.hInstance = inst;
    wc.lpszClassName = L"PR2LauncherGUI";
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1);
    RegisterClassW(&wc);

    HWND hwnd = CreateWindowW(L"PR2LauncherGUI", W("Port Royale 2 启动器"),
                              WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU |
                              WS_MINIMIZEBOX,
                              CW_USEDEFAULT, CW_USEDEFAULT, 370, 210,
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
