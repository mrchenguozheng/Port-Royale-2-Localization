/* pr2_launcher.cpp -- 注入启动器 (独立工具, 非游戏文件)
 * 以挂起方式启动同目录下的 PR2.exe, 把同目录 PR2TextSource.dll 注入后恢复执行。
 * 全程不修改任何游戏文件、不修改 PR2.exe。
 *
 * 流程: CreateProcessA(CREATE_SUSPENDED) -> 远程 LoadLibraryA -> ResumeThread
 * DLL 的加载结果通过远程线程的返回值判断（见文件末尾 exit==0 分支）。
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

int main(void) {
    char self[MAX_PATH];
    UseUtf8Console();
    GetModuleFileNameA(NULL, self, MAX_PATH);

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
