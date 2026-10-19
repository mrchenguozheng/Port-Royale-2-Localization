/* pr2_launcher.cpp -- 注入启动器 (独立工具, 非游戏文件)
 * 以挂起方式启动同目录下的 PR2.exe, 把同目录 PR2TextSource.dll 注入后恢复执行。
 * 全程不修改任何游戏文件、不修改 PR2.exe。
 *
 * 流程: CreateProcessA(CREATE_SUSPENDED) -> 远程 LoadLibraryA -> ResumeThread
 * DLL 的加载结果通过远程线程的返回值判断（见文件末尾 exit==0 分支）。
 *
 * 可选参数:
 *   --lang=<代码>  这一次启动用 PR2Packs\<代码>.txt，优先于 locale.ini。
 *                  通过子进程环境的 PR2_PACK_LANG 传递，不写任何文件；
 *                  不带这个参数时行为与从前完全一样。
 */
#include <windows.h>
#include <stdio.h>
#include <string.h>

/* 源文件是 UTF-8（cl 用 /utf-8 编译），所以 printf 送出去的是 UTF-8 字节。
 * 控制台默认代码页是 936，直接 printf 会显示成乱码，必须先切到 UTF-8。 */
static void UseUtf8Console(void) {
    SetConsoleOutputCP(CP_UTF8);
    SetConsoleCP(CP_UTF8);
}

static void SiblingPath(char* out, const char* self, const char* name) {
    char tmp[MAX_PATH];
    strcpy(tmp, self);
    char* p = strrchr(tmp, '\\');
    if (p) strcpy(p + 1, name);
    else strcpy(tmp, name);
    strcpy(out, tmp);
}

/* 语言代码只允许字母数字和连字符，且不能是 "." 或 ".." —— 它要拼进
 * PR2Packs\<code>.txt 这样的路径，放任 "../" 就是目录穿越。
 * 返回 1 表示可用，0 表示不可用。 */
static int ValidLangCode(const char* s) {
    const char* p;
    if (!s || !*s) return 0;
    if (strcmp(s, ".") == 0 || strcmp(s, "..") == 0) return 0;
    for (p = s; *p; p++) {
        char c = *p;
        int okChar = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
                  || (c >= '0' && c <= '9') || c == '-';
        if (!okChar) return 0;
    }
    return 1;
}

int main(int argc, char** argv) {
    char self[MAX_PATH];
    int  i;
    const char* lang = NULL;

    UseUtf8Console();
    GetModuleFileNameA(NULL, self, MAX_PATH);

    /* --lang=xx：只影响这一次启动。GUI 用它来「这次用另一种语言跑」，
     * 不写任何文件；不带这个参数时行为与从前完全一样。 */
    for (i = 1; i < argc; i++) {
        if (strncmp(argv[i], "--lang=", 7) == 0) {
            lang = argv[i] + 7;
        } else if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
            printf("[PR2Launch] 用法: %s [--lang=<代码>]\n", "PR2Launcher.exe");
            printf("[PR2Launch]   --lang  这一次启动用哪个语言包，\n");
            printf("[PR2Launch]           覆盖 PR2Packs\\locale.ini 的 language=。\n");
            printf("[PR2Launch]           不带这个参数就用 locale.ini 里的语言。\n");
            return 0;
        }
    }
    if (lang && !ValidLangCode(lang)) {
        printf("[PR2Launch] --lang 的值不合法: %s\n", lang);
        printf("[PR2Launch] 只允许字母、数字和连字符，例如 --lang=zh。\n");
        return 1;
    }

    char exePath[MAX_PATH];
    SiblingPath(exePath, self, "PR2.exe");

    char dllPath[MAX_PATH];
    SiblingPath(dllPath, self, "PR2TextSource.dll");

    if (GetFileAttributesA(exePath) == INVALID_FILE_ATTRIBUTES) {
        printf("[PR2Launch] 同目录下找不到 PR2.exe: %s\n", exePath);
        return 1;
    }
    if (GetFileAttributesA(dllPath) == INVALID_FILE_ATTRIBUTES) {
        printf("[PR2Launch] 同目录下找不到 PR2TextSource.dll: %s\n", dllPath);
        return 1;
    }

    /* 传给子进程：下面 CreateProcessA 的环境参数是 NULL，意思是
     * 「继承我的」，所以在这里设一次 PR2.exe 就有了。DLL 在
     * LoadEditFile() 里读它，读不到就退回 locale.ini。 */
    if (lang) {
        SetEnvironmentVariableA("PR2_PACK_LANG", lang);
        printf("[PR2Launch] 本次使用语言包: %s.txt (覆盖 locale.ini)\n", lang);
    }

    STARTUPINFOA si = {0}; si.cb = sizeof(si);
    PROCESS_INFORMATION pi = {0};
    if (!CreateProcessA(exePath, NULL, NULL, NULL, FALSE, CREATE_SUSPENDED, NULL, NULL, &si, &pi)) {
        printf("[PR2Launch] 启动 PR2.exe 失败 (错误 %lu)\n", GetLastError());
        return 1;
    }

    size_t n = strlen(dllPath) + 1;
    void* p = VirtualAllocEx(pi.hProcess, NULL, n, MEM_COMMIT, PAGE_READWRITE);
    if (!p) { printf("[PR2Launch] VirtualAllocEx 失败 %lu\n", GetLastError()); return 1; }
    if (!WriteProcessMemory(pi.hProcess, p, dllPath, n, NULL)) {
        printf("[PR2Launch] WriteProcessMemory 失败 %lu\n", GetLastError()); return 1;
    }
    HMODULE k32 = GetModuleHandleA("kernel32.dll");
    FARPROC loadLib = GetProcAddress(k32, "LoadLibraryA");
    HANDLE th = CreateRemoteThread(pi.hProcess, NULL, 0, (LPTHREAD_START_ROUTINE)loadLib, p, 0, NULL);
    if (!th) { printf("[PR2Launch] CreateRemoteThread 失败 %lu\n", GetLastError()); return 1; }
    WaitForSingleObject(th, INFINITE);
    DWORD exit = 0;
    GetExitCodeThread(th, &exit);
    CloseHandle(th);
    ResumeThread(pi.hThread);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);

    if (exit == 0) {
        printf("[PR2Launch] PR2TextSource.dll 注入失败 (LoadLibrary 返回 NULL, 错误 %lu)\n", GetLastError());
        printf("[PR2Launch] 提示: 游戏可能因缺少 VC 运行库或 DLL 缺失而未能加载补丁。\n");
        return 1;
    }
    printf("[PR2Launch] 语言包已注入, PR2.exe 启动中...\n");
    return 0;
}
