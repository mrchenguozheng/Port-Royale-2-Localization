# fontstitch

给游戏原版的**拉丁字体补上中文字形**，用于中文化：拉丁字形、字宽和 name 表保持原样，只把翻译用到的汉字追加进去。

面向的场景就是：游戏内嵌字体（如 Port Royale 2 的 El Greco / Tiepolo / Arial）只能显示西文，需要让它在不改动英文、法文排版的前提下显示中文。

```
fontstitch/
├── fontstitch.py    augment（补汉字）/ extract（拆 TTC）/ validate（结构校验）
├── fontsubset.py    可选：裁剪任意字体（封装 pyftsubset）
├── fontverify.py    可选：字体信息 / 逐字形校验 / UPM 缩放（需要 fontTools）
├── presets.toml     四组配对偏好的记录
└── README.md
```

## 快速开始

```bash
# 在 fontstitch/ 目录下执行；把翻译用到的汉字补进原版字体
python fontstitch.py augment ARIAL.TTF C:\Windows\Fonts\msyh.ttc ARIAL-zh.ttf \
  --text "糖价上涨了三成。" --donor-index 0

# 几千字用文件
python fontstitch.py augment ARIAL.TTF C:\Windows\Fonts\msyh.ttc ARIAL-zh.ttf \
  --text-file 用字.txt --encoding gbk --donor-index 0
```

输出：

```
family     : Arial
characters : 8 added, 0 already in base, 0 missing
glyphs     : 1329 (base 1320 + appended 9)
cmap       : 1194 code points
size       : 0.25 MB
latin      : 0 glyph(s) changed, 0 base code point(s) remapped
RESULT     : OK
```

`latin changed` 和 `base code point remapped` 必须为 0；不为 0 说明原版字形被动了。

## augment 的行为

1. 读取用字（`--text` / `--text-file` / `--chars` / `--scan`）
2. 只挑 base 字体**没有**的码位去 donor 里找——原版已有的字符（包括英文、法文、数字）一律不动
3. 把 donor 裁剪到这些字符，剥离 hinting，丢掉 GSUB/GPOS/GDEF
4. 追加字形到 base，重建 cmap/loca/hmtx/head/maxp
5. **name 表原样保留**（族名、Full Name、PostScript 名都不变），游戏按原名加载不会受影响
6. 逐字形比对 base 部分，报告是否有改动

## 参数

| 参数 | 说明 |
|---|---|
| `--text "见字如面"` | 直接给字符串（少量字时用） |
| `--text-file 用字.txt` | 从文件读（几千字用这个） |
| `--chars U+4E00-4E10` | 码位范围 |
| `--scan 目录` | 扫描文本文件/目录，自动收集用字 |
| `--scan-encoding gbk` | 扫描文件的编码（auto / utf-8 / utf-16 / gbk / cp1252） |
| `--encoding gbk` | `--text-file` 的编码（默认 utf-8-sig） |
| `--donor-index 0` | donor 是 `.ttc` 时取第几个字面 |
| `--family "Arial"` | 改族名（默认保持 base 原族名） |
| `--missing-report 缺字.txt` | 有缺字时导出清单，退出码 1 |
| `--check` | 结束后跑一遍结构校验 |

## 实测（补 2,004 个汉字，另 17 个在原字体中已有）

| 原版字体 | 最终字形数 | 拉丁改动 | 族名/PS 名 | 体积 |
|---|---|---|---|---|
| ElGreco | 2,253 | 0 | 原样 | 1.26 MB |
| Tiepolo-Black | 2,252 | 0 | 原样 | 0.93 MB |
| Tiepolo-Bold | 2,252 | 0 | 原样 | 0.93 MB |
| Arial | 3,325 | 0 | 原样 | 0.83 MB |

追加的字形数会比字符数多 1–2 个（donor 的 `.notdef`，以及复合字形可能带进来的组件）。
Arial 补满整个 GB2312（6,763 字）实测 **2.13 MB / 8,084 字形**。

## 选哪个中文 donor

| 原版字体 | 角色 | donor（我的偏好） | 理由 |
|---|---|---|---|
| ElGreco | 装饰标题 | 钟齐志莽行书 | 行书气质配花体；实测覆盖全部 6,763 个 GB2312 字 |
| Tiepolo-Black | 重标题 | 思源宋体 Heavy | 字重最匹配；7,081 字形子集，GB2312 覆盖 6,585/6,763 |
| Tiepolo-Bold | 标题 | 华文中宋 | 覆盖 24k 字符，最稳 |
| Arial | 正文/UI | 微软雅黑 | 同为 2048 UPM，免缩放；12px 黑体最清晰 |

这四组同时记录在 [`presets.toml`](presets.toml) 里（含 donor 路径与 `donor_index`），作为配置参考；`augment` 仍按显式路径调用，不依赖它。

## 限制

| 限制 | 说明 |
|---|---|
| **augment 只支持 glyf** | 底字和 donor 都必须是 TrueType 轮廓；CFF/OTF 需要先自行转成 TTF（本项目不做转换） |
| **UPM 必须一致** | 不一致先用 `fontverify.py scale` 缩放 donor（缩放会丢 kern 表；TTC 先用 `extract` 拆出来） |
| **hinting** | 保留 base 的 hinting，追加的汉字不带 hinting；12px 下汉字会偏软 |
| **不保留竖排表** | `vhea/vmtx` 丢弃，横排不受影响 |
| **编码** | 工具按 Unicode 处理；游戏若用 CP1252/GBK，`--scan` 指定 `--scan-encoding`，`--text-file` 指定 `--encoding` |

## 附带工具

```bash
# 从 .ttc 拆出单个字面
python fontstitch.py extract msyh.ttc 0 YaHei.ttf

# 结构校验：表排序、校验和、cmap/loca/hmtx/name
python fontstitch.py validate 输出.ttf

# 可选：按用字裁剪任意字体（封装 pyftsubset）
python fontsubset.py 输入.ttf 输出.ttf --text-file 用字.txt

# 可选：查看字体信息 / 把 donor 缩放到目标 UPM（需 fontTools）
python fontverify.py info 输出.ttf
python fontverify.py scale donor.ttf donor-1000.ttf 1000
```

## 路径与环境变量

`fontstitch.py` 的路径参数（base / donor / out / `--text-file` / `--scan` / `--missing-report`）支持 `%WINDIR%`、`%LOCALAPPDATA%`、`${VAR}`、`${VAR:-默认}`、`~`；相对路径按当前工作目录解析。

## 授权

修改字体属于衍生作品。OFL 字体允许修改但需改名；商业字库（Berthold、微软系统字体等）通常禁止修改与再分发。自用没问题，对外发布前先看原字体许可。
