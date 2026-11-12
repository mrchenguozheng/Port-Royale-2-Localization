/* pr2_fonts.h -- 运行时共用的字体契约。
 *
 * 四个文件名是游戏写死的；launcher、GUI 和字体检查都必须用同一份，
 * 避免以后改字体名时漏掉一处。
 */
#ifndef PR2_FONTS_H
#define PR2_FONTS_H

#include <windows.h>
#include <stdio.h>

#define PR2_FONT_COUNT 4

static const char* const PR2_FONT_NAMES[PR2_FONT_COUNT] = {
    "ARIAL.TTF",
    "ELGRECO_.TTF",
    "Tiepolo_black.ttf",
    "Tiepolo_bold.ttf"
};

/* 检查 fonts\<语言>\ 下四个 TTF 是否齐全。 */
static int pr2_language_fonts_complete(const char* root, const char* lang) {
    if (!root || !lang || !*lang) return 0;
    for (int i = 0; i < PR2_FONT_COUNT; i++) {
        char path[MAX_PATH];
        snprintf(path, sizeof(path), "%s\\fonts\\%s\\%s", root, lang,
                 PR2_FONT_NAMES[i]);
        if (GetFileAttributesA(path) == INVALID_FILE_ATTRIBUTES) return 0;
    }
    return 1;
}

#endif
