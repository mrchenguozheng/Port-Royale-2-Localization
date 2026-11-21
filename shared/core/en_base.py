"""英文基准的两处结构缺口。

`en.gog_1.1.2.3.toml` 在两处段落分隔处漏了一个 `<n>`；de / es / fr / pl / ru
五门零售版以及 `build/ref/clean/en-clean.toml` 都是两个，所以各语言的译文按
两个写。

`build/ref/clean/` 是 `ref_clean.py` 的派生件，跟 `build/` 一起 gitignore。
干净 clone（CI）上没有 clean，`text_lint.py` 与 `merge_batches.py` 都会退回
en 原件，于是这两条把**所有语言**判成「模板不一致」/「Extra tag|」——CI 的
Static checks 就是这么红的（run 44747642507）。基准口径不能依赖构建产物，
所以修正写进代码：有 clean 也补、没有也补，两边判据一致。

`ref_clean.py` 只报不修（多数票切点要靠人定），它重生成的 clean 也缺这两处，
这里一并兜住。
"""

#: 键 → (原件片段, 补齐后的片段)。片段唯一且短，原串变了就原样跳过，不猜。
BASE_FIXUPS = {
    "0x0cf7abf0": ("completed.<n>Go", "completed.<n><n>Go"),
    "0xdb0108dd": ("convoy.<n>Now", "convoy.<n><n>Now"),
}

#: 补齐后整条里应有的 `<n>` 总数（零售版多数票）。补完对不上就直接报错，
#: 免得基准悄悄漂了、又把整片判成「模板不一致」。
EXPECTED = {"0x0cf7abf0": 2, "0xdb0108dd": 4}


def apply(doc):
    """就地补齐两处 `<n>`，返回同一个 dict；对不上就抛 ValueError。"""
    for key, (old, new) in BASE_FIXUPS.items():
        value = doc.get(key)
        if isinstance(value, str) and old in value and new not in value:
            doc[key] = value.replace(old, new, 1)
        padded = doc.get(key)
        if isinstance(padded, str) and padded.count("<n>") != EXPECTED[key]:
            raise ValueError("基准 %s 的 `<n>` 有 %d 个，应为 %d" % (
                key, padded.count("<n>"), EXPECTED[key]))
    return doc
