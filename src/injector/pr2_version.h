/* pr2_version.h -- 运行时版本与语言包最低版本检查。
 *
 * 每个语言包头部可以写：
 *   # pack-meta min_runtime=1
 * 缺省按 1 处理；大于当前运行时版本时，launcher/GUI 拒绝启动。
 */
#ifndef PR2_VERSION_H
#define PR2_VERSION_H

#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PR2_RUNTIME_VERSION 1

static int pr2_pack_min_runtime(const char* root, const char* lang) {
    char path[MAX_PATH], line[1024];
    if (!root || !lang || !*lang) return 1;
    snprintf(path, sizeof(path), "%s\\PR2Packs\\%s.txt", root, lang);
    FILE* f = fopen(path, "rb");
    if (!f) return 1;
    int version = 1;
    for (int n = 0; n < 64 && fgets(line, sizeof(line), f); n++) {
        char* p = line;
        if (strncmp(p, "# pack-meta ", 12) != 0) {
            if (*p == '#' || *p == '\r' || *p == '\n' || !*p) continue;
            break;
        }
        p += 12;
        if (strncmp(p, "min_runtime=", 12) == 0) {
            int v = atoi(p + 12);
            if (v > version) version = v;
        }
    }
    fclose(f);
    return version;
}

static int pr2_pack_runtime_ok(const char* root, const char* lang) {
    return pr2_pack_min_runtime(root, lang) <= PR2_RUNTIME_VERSION;
}

#endif
