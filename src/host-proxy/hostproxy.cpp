// Steam host DLL proxy: takes over the Log export of Ascaron.Logging-2.6.dll.
//
// PR2.exe statically imports Ascaron.Logging-2.6.dll and uses only Log.
// Deployment:
//   original -> Ascaron.Logging-2.6.orig.dll
//   this proxy -> Ascaron.Logging-2.6.dll
//
// The proxy forwards Log to .orig.dll and starts a thread in DllMain.
// After A2dLib-2.20A.dll is loaded it loads PR2LocalizationCore.dll, so the
// Core initialization does not block the host loader.

#include <windows.h>
#include <stdio.h>
#include <string.h>

extern "C" void* g_pr2_log = nullptr;
static HINSTANCE g_self = nullptr;

static void RawLog(const wchar_t* dir, const char* msg) {
    wchar_t logdir[MAX_PATH];
    _snwprintf_s(logdir, MAX_PATH, _TRUNCATE, L"%s\\PR2Localization\\logs", dir);
    CreateDirectoryW(logdir, nullptr);
    wchar_t path[MAX_PATH];
    _snwprintf_s(path, MAX_PATH, _TRUNCATE, L"%s\\proxy.log", logdir);
    HANDLE h = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ | FILE_SHARE_WRITE,
                           nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h != INVALID_HANDLE_VALUE) {
        DWORD n = 0;
        WriteFile(h, msg, (DWORD)strlen(msg), &n, nullptr);
        WriteFile(h, "\r\n", 2, &n, nullptr);
        CloseHandle(h);
    }
}

extern "C" void EnsureOriginal() {
    if (g_pr2_log) return;
    wchar_t module_path[MAX_PATH];
    GetModuleFileNameW(g_self, module_path, MAX_PATH);
    wchar_t dir[MAX_PATH];
    wcscpy_s(dir, module_path);
    wchar_t* slash = wcsrchr(dir, L'\\');
    if (slash) *slash = 0;
    wchar_t orig[MAX_PATH];
    _snwprintf_s(orig, MAX_PATH, _TRUNCATE, L"%s\\Ascaron.Logging-2.6.orig.dll", dir);
    HMODULE h = LoadLibraryW(orig);
    if (h) {
        g_pr2_log = (void*)GetProcAddress(h, "Log");
        RawLog(dir, "[host] original Log resolved");
    } else {
        RawLog(dir, "[host] original Log load failed");
    }
}

extern "C" __declspec(dllexport) __declspec(naked) void Log() {
    __asm {
        pushfd
        pushad
        call EnsureOriginal
        popad
        popfd
        jmp dword ptr [g_pr2_log]
    }
}

static DWORD WINAPI Bootstrap(LPVOID param) {
    HMODULE self = (HMODULE)param;
    wchar_t module_path[MAX_PATH];
    GetModuleFileNameW(self, module_path, MAX_PATH);
    wchar_t dir[MAX_PATH];
    wcscpy_s(dir, module_path);
    wchar_t* slash = wcsrchr(dir, L'\\');
    if (slash) *slash = 0;

    RawLog(dir, "[host] bootstrap thread start");
    for (int i = 0; i < 100; ++i) {
        if (GetModuleHandleA("A2dLib-2.20A.dll")) break;
        Sleep(100);
    }
    RawLog(dir, "[host] wait for A2dLib done");
    Sleep(50);

    wchar_t core[MAX_PATH];
    _snwprintf_s(core, MAX_PATH, _TRUNCATE, L"%s\\PR2LocalizationCore.dll", dir);
    HMODULE h = LoadLibraryW(core);
    if (!h) {
        char buf[128];
        _snprintf_s(buf, sizeof(buf), _TRUNCATE, "[host] core load failed: %lu", GetLastError());
        RawLog(dir, buf);
    } else {
        RawLog(dir, "[host] loaded PR2LocalizationCore.dll");
    }
    return 0;
}

BOOL WINAPI DllMain(HINSTANCE hinst, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        g_self = hinst;
        DisableThreadLibraryCalls(hinst);
        wchar_t module_path[MAX_PATH];
        GetModuleFileNameW(hinst, module_path, MAX_PATH);
        wchar_t dir[MAX_PATH];
        wcscpy_s(dir, module_path);
        wchar_t* slash = wcsrchr(dir, L'\\');
        if (slash) *slash = 0;
        RawLog(dir, "[host] DllMain loaded");
        CreateThread(nullptr, 0, Bootstrap, (LPVOID)hinst, 0, nullptr);
    }
    return TRUE;
}
