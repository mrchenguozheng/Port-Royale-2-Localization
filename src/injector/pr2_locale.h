/* pr2_locale.h -- 运行时共用的 locale.ini 读取/写回。
 *
 * 只有 GUI 会在启动成功后写回；launcher 和 DLL 只读。
 * 这样不会在 launcher.ini 里再存一份“当前语言”。
 */
#ifndef PR2_LOCALE_H
#define PR2_LOCALE_H

#include <windows.h>
#include <stdio.h>
#include <string.h>

static void pr2_locale_trim(char* s) {
    char* p = s;
    while (*p == ' ' || *p == '\t') p++;
    if (p != s) memmove(s, p, strlen(p) + 1);
    size_t n = strlen(s);
    while (n && (s[n-1] == '\r' || s[n-1] == '\n' ||
                 s[n-1] == ' ' || s[n-1] == '\t')) {
        s[--n] = 0;
    }
}

static int pr2_read_locale_language(const char* root, char* out, int cap) {
    char path[MAX_PATH], line[512];
    if (!root || !out || cap <= 0) return 0;
    out[0] = 0;
    snprintf(path, sizeof(path), "%s\\PR2Packs\\locale.ini", root);
    FILE* f = fopen(path, "rb");
    if (!f) return 0;
    int found = 0;
    while (fgets(line, sizeof(line), f)) {
        char* p = line;
        pr2_locale_trim(p);
        if (strncmp(p, "language", 8) != 0) continue;
        p += 8;
        while (*p == ' ' || *p == '\t') p++;
        if (*p != '=') continue;
        p++;
        while (*p == ' ' || *p == '\t') p++;
        char* e = p;
        while (*e && *e != '\r' && *e != '\n' && *e != ' ' && *e != '\t') e++;
        *e = 0;
        if (*p) {
            strncpy(out, p, cap - 1);
            out[cap - 1] = 0;
            found = 1;
        }
        break;
    }
    fclose(f);
    return found;
}

static int pr2_write_locale_language(const char* root, const char* lang) {
    char path[MAX_PATH], tmp[MAX_PATH], line[1024];
    if (!root || !lang || !*lang) return 0;
    snprintf(path, sizeof(path), "%s\\PR2Packs\\locale.ini", root);
    snprintf(tmp, sizeof(tmp), "%s.tmp", path);
    int replaced = 0;
    FILE* in = fopen(path, "rb");
    FILE* out = fopen(tmp, "wb");
    if (!out) { if (in) fclose(in); return 0; }
    if (in) {
        while (fgets(line, sizeof(line), in)) {
            char probe[1024];
            strncpy(probe, line, sizeof(probe) - 1);
            probe[sizeof(probe) - 1] = 0;
            pr2_locale_trim(probe);
            if (strncmp(probe, "language", 8) == 0) {
                char* p = probe + 8;
                while (*p == ' ' || *p == '\t') p++;
                if (*p == '=') {
                    fprintf(out, "language=%s\n", lang);
                    replaced = 1;
                    continue;
                }
            }
            fputs(line, out);
        }
        fclose(in);
    }
    if (!replaced) fprintf(out, "language=%s\n", lang);
    fclose(out);
    if (!MoveFileExA(tmp, path, MOVEFILE_REPLACE_EXISTING)) {
        remove(tmp);
        return 0;
    }
    return 1;
}

#endif
