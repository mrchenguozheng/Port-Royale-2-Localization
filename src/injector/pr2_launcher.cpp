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
#include <wincrypt.h>
#include <stdio.h>
#include <string.h>
#pragma comment(lib, "advapi32.lib")

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

static void DirOf(const char* path, char* out) {
    strcpy(out, path);
    char* p = strrchr(out, '\\');
    if (p) *p = '\0';
    else strcpy(out, ".");
}

/* 读 PR2Packs\locale.ini 的 language=；读不到返回 0。 */
static int ReadLocaleLang(const char* self, char* out, size_t cap) {
    char root[MAX_PATH], ini[MAX_PATH], line[512];
    DirOf(self, root);
    snprintf(ini, sizeof(ini), "%s\\PR2Packs\\locale.ini", root);
    FILE* f = fopen(ini, "rb");
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
        char* end = p;
        while (*end && *end != '\r' && *end != '\n' && *end != ' ' && *end != '\t') end++;
        *end = '\0';
        if (*p && strlen(p) < cap) {
            strcpy(out, p);
            found = 1;
        }
        break;
    }
    fclose(f);
    return found;
}

/* 把 fonts\<语言>\*.ttf 复制到 fonts\ 根目录，供游戏按固定文件名加载。
 * 发行包只放子目录；启动器在 CreateProcess 之前做这一步。 */
static int CopyFontSet(const char* self, const char* lang) {
    char root[MAX_PATH], langDir[MAX_PATH], pattern[MAX_PATH], dstDir[MAX_PATH];
    DirOf(self, root);
    snprintf(langDir, sizeof(langDir), "%s\\fonts\\%s", root, lang);
    if (GetFileAttributesA(langDir) == INVALID_FILE_ATTRIBUTES) return 0;
    snprintf(dstDir, sizeof(dstDir), "%s\\fonts", root);

    snprintf(pattern, sizeof(pattern), "%s\\*.ttf", langDir);
    WIN32_FIND_DATAA fd;
    HANDLE h = FindFirstFileA(pattern, &fd);
    if (h == INVALID_HANDLE_VALUE) return 0;

    int copied = 0;
    do {
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) continue;
        char src[MAX_PATH], dst[MAX_PATH];
        snprintf(src, sizeof(src), "%s\\%s", langDir, fd.cFileName);
        snprintf(dst, sizeof(dst), "%s\\%s", dstDir, fd.cFileName);
        if (CopyFileA(src, dst, FALSE)) {
            copied++;
        } else {
            printf("[PR2Launch] 字体复制失败: %s (错误 %lu)\n", src, GetLastError());
        }
    } while (FindNextFileA(h, &fd));
    FindClose(h);
    if (copied) {
        printf("[PR2Launch] 已切换字体: fonts\\%s\\ (%d 个 TTF)\n", lang, copied);
    }
    return copied;
}

/* 原版字体备份：只在第一次替换前做一次，且只认已知的原版大小。
 * 这样即使用户已经用 Noto 覆盖过根目录，也不会把 Noto 误存成原版。 */
static const char* ORIG_FONT_NAMES[4] = {
    "ARIAL.TTF", "ELGRECO_.TTF", "Tiepolo_black.ttf", "Tiepolo_bold.ttf"
};
static const DWORD ORIG_FONT_SIZES[4] = {
    296712, 65680, 52876, 53120
};
static const char* ORIG_FONT_HASHES[4] = {
    "1906a771ed879a5de75a3ff552fbad533827fe7b39e18319ce9d9ae134c346c7",
    "f3715e59051796963fc6569d85c16b9abfd6eaf949bcc8a9578c1fe0a423acf9",
    "267f1a2de1c1e738202ca31008c587e045d25268c93662d8fd80b79615d314e7",
    "fd10e52dd5040de4fc00e09919b5e5e360039360deff5bfc2219ffa61061c465"
};

static int FileSha256(const char* path, char out[65]) {
    HANDLE f = CreateFileA(path, GENERIC_READ,
                           FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
                           OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (f == INVALID_HANDLE_VALUE) return 0;
    HCRYPTPROV prov = 0;
    HCRYPTHASH hash = 0;
    BYTE digest[32];
    DWORD dlen = sizeof(digest);
    int ok = 0;
    if (CryptAcquireContextA(&prov, NULL, NULL, PROV_RSA_AES, CRYPT_VERIFYCONTEXT)) {
        if (CryptCreateHash(prov, CALG_SHA_256, 0, 0, &hash)) {
            BYTE buf[65536];
            DWORD got = 0;
            while (ReadFile(f, buf, sizeof(buf), &got, NULL) && got > 0) {
                if (!CryptHashData(hash, buf, got, 0)) break;
            }
            if (CryptGetHashParam(hash, HP_HASHVAL, digest, &dlen, 0)) {
                for (DWORD i = 0; i < dlen; i++) sprintf(out + i * 2, "%02x", digest[i]);
                out[dlen * 2] = 0;
                ok = 1;
            }
            CryptDestroyHash(hash);
        }
        CryptReleaseContext(prov, 0);
    }
    CloseHandle(f);
    return ok;
}

static DWORD FileSizeOf(const char* path) {
    WIN32_FILE_ATTRIBUTE_DATA d;
    if (!GetFileAttributesExA(path, GetFileExInfoStandard, &d)) return 0xFFFFFFFF;
    if (d.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) return 0xFFFFFFFF;
    return d.nFileSizeLow;
}

static int LooksLikeOriginalFonts(const char* root) {
    for (int i = 0; i < 4; i++) {
        char p[MAX_PATH], hex[65];
        snprintf(p, sizeof(p), "%s\\fonts\\%s", root, ORIG_FONT_NAMES[i]);
        if (FileSizeOf(p) != ORIG_FONT_SIZES[i]) return 0;
        if (!FileSha256(p, hex) || _stricmp(hex, ORIG_FONT_HASHES[i]) != 0) {
            printf("[PR2Launch] 字体大小像原版但 SHA-256 不匹配，跳过备份: %s\n",
                   ORIG_FONT_NAMES[i]);
            return 0;
        }
    }
    return 1;
}

static void BackupOriginalFonts(const char* self) {
    char root[MAX_PATH], bak[MAX_PATH];
    DirOf(self, root);
    snprintf(bak, sizeof(bak), "%s\\fonts\\_original", root);
    if (GetFileAttributesA(bak) != INVALID_FILE_ATTRIBUTES) return;
    if (!LooksLikeOriginalFonts(root)) {
        printf("[PR2Launch] fonts 根目录不是原版字体，跳过原版备份\n");
        return;
    }
    CreateDirectoryA(bak, NULL);
    int n = 0;
    for (int i = 0; i < 4; i++) {
        char src[MAX_PATH], dst[MAX_PATH];
        snprintf(src, sizeof(src), "%s\\fonts\\%s", root, ORIG_FONT_NAMES[i]);
        snprintf(dst, sizeof(dst), "%s\\%s", bak, ORIG_FONT_NAMES[i]);
        if (CopyFileA(src, dst, FALSE)) n++;
    }
    if (n == 4) printf("[PR2Launch] 已备份原版字体: fonts\\_original\\\n");
    else printf("[PR2Launch] 原版字体备份不完整（%d/4）\n", n);
}

static int RestoreOriginalFonts(const char* self) {
    char root[MAX_PATH], bak[MAX_PATH];
    DirOf(self, root);
    snprintf(bak, sizeof(bak), "%s\\fonts\\_original", root);
    if (GetFileAttributesA(bak) == INVALID_FILE_ATTRIBUTES) return 0;
    int n = 0;
    for (int i = 0; i < 4; i++) {
        char src[MAX_PATH], dst[MAX_PATH], hex[65];
        snprintf(src, sizeof(src), "%s\\%s", bak, ORIG_FONT_NAMES[i]);
        snprintf(dst, sizeof(dst), "%s\\fonts\\%s", root, ORIG_FONT_NAMES[i]);
        if (!FileSha256(src, hex) || _stricmp(hex, ORIG_FONT_HASHES[i]) != 0) {
            printf("[PR2Launch] 原版备份哈希不匹配，拒绝恢复: %s\n",
                   ORIG_FONT_NAMES[i]);
            continue;
        }
        if (CopyFileA(src, dst, FALSE)) n++;
    }
    if (n) printf("[PR2Launch] 已恢复原版字体 (%d/4)\n", n);
    return n;
}

/* 语言代码只允许字母数字、连字符和下划线，且不能是 "." 或 ".." —— 它要
 * 拼进 PR2Packs\<code>.txt 这样的路径，放任 "../" 就是目录穿越。
 * 返回 1 表示可用，0 表示不可用。
 *
 * 【下划线必须放行】之前只允许字母数字和连字符，而编辑器/文档里写的是
 * "字母 / 数字 / - / _"。于是 test_en 这种名字编译、部署都成功，点「启动
 * 游戏」时却被这里判成不合法、启动器直接退出 —— 现象是黑框一闪、游戏
 * 根本没起来，而错误只打在启动器自己的控制台里，一闪就没。
 * 下划线在文件名里完全安全，没有理由拦它。 */
static int ValidLangCode(const char* s) {
    const char* p;
    if (!s || !*s) return 0;
    if (strlen(s) >= 64) return 0;          /* 与下面的 MAX_PATH 拼接留余量 */
    if (strcmp(s, ".") == 0 || strcmp(s, "..") == 0) return 0;
    for (p = s; *p; p++) {
        char c = *p;
        int okChar = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z')
                  || (c >= '0' && c <= '9') || c == '-' || c == '_';
        if (!okChar) return 0;
    }
    return 1;
}

int main(int argc, char** argv) {
    char self[MAX_PATH];
    int  i;
    const char* lang = NULL;
    int vanilla = 0;
    int noFontCopy = 0;

    UseUtf8Console();
    GetModuleFileNameA(NULL, self, MAX_PATH);

    /* --lang=xx：只影响这一次启动。GUI 用它来「这次用另一种语言跑」，
     * 不写任何文件；不带这个参数时行为与从前完全一样。 */
    for (i = 1; i < argc; i++) {
        if (strncmp(argv[i], "--lang=", 7) == 0) {
            lang = argv[i] + 7;
        } else if (strcmp(argv[i], "--vanilla") == 0) {
            vanilla = 1;
        } else if (strcmp(argv[i], "--no-font-copy") == 0) {
            noFontCopy = 1;
        } else if (strcmp(argv[i], "--help") == 0 || strcmp(argv[i], "-h") == 0) {
            printf("[PR2Launch] 用法: %s [--lang=<代码>] [--vanilla]\n", "PR2Launcher.exe");
            printf("[PR2Launch]   --lang     这一次启动用哪个语言包，\n");
            printf("[PR2Launch]              覆盖 PR2Packs\\locale.ini 的 language=。\n");
            printf("[PR2Launch]   --vanilla  恢复原版字体后直接启动 PR2.exe，不注入。\n");
            printf("[PR2Launch]   --no-font-copy  不复制字体（配合 PR2_FONT_DIR 做重定向测试）。\n");
            return 0;
        }
    }
    if (lang && !ValidLangCode(lang)) {
        printf("[PR2Launch] --lang 的值不合法: %s\n", lang);
        printf("[PR2Launch] 只允许字母、数字、连字符和下划线，例如 --lang=zh 或 --lang=zh-TW。\n");
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

    BackupOriginalFonts(self);

    if (vanilla) {
        RestoreOriginalFonts(self);
        STARTUPINFOA vsi = {0}; vsi.cb = sizeof(vsi);
        PROCESS_INFORMATION vpi = {0};
        char vdir[MAX_PATH];
        DirOf(self, vdir);
        if (!CreateProcessA(exePath, NULL, NULL, NULL, FALSE, 0, NULL, vdir,
                            &vsi, &vpi)) {
            printf("[PR2Launch] 启动原版 PR2.exe 失败 (错误 %lu)\n", GetLastError());
            return 1;
        }
        CloseHandle(vpi.hThread);
        CloseHandle(vpi.hProcess);
        printf("[PR2Launch] 已恢复原版字体，启动原版 PR2.exe（未注入）\n");
        return 0;
    }

    if (GetFileAttributesA(dllPath) == INVALID_FILE_ATTRIBUTES) {
        printf("[PR2Launch] 同目录下找不到 PR2TextSource.dll: %s\n", dllPath);
        return 1;
    }

    /* 字体按语言放在 fonts\<语言>\；游戏只认 fonts\ 根目录下的固定文件名，
     * 所以在启动前把目标语言那一套复制到根目录。没有子目录时保持旧行为。 */
    if (!noFontCopy) {
        char localeLang[64];
        const char* fontLang = lang;
        if (!fontLang && ReadLocaleLang(self, localeLang, sizeof(localeLang))) {
            fontLang = localeLang;
        }
        if (fontLang && ValidLangCode(fontLang)) {
            CopyFontSet(self, fontLang);
        }
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
    char gameDir[MAX_PATH];
    DirOf(self, gameDir);
    if (!CreateProcessA(exePath, NULL, NULL, NULL, FALSE, CREATE_SUSPENDED,
                        NULL, gameDir, &si, &pi)) {
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
