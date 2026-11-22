# Noto 源字体（可选入库目录）

这个目录是字体兜底的**项目内落点**：GitHub runner 上没有装 Noto 时，构建会
先看这里，其次看 `build\cache\noto-src`（下载缓存），最后才看系统字体目录。

平时不用往这里放文件——缺字体时执行：

```
python src\tools\font\fetch_noto_fonts.py --langs zh,ja --fetch
```

它会按 `src\fonts-sources.toml` 下载可变字体，再按需要的字重实例化成静态
文件，默认落在 `build\cache\noto-src`（不入库，CI 用 actions/cache 持久）。

需要完全离线、或要让字体跟着仓库走时，把清单里的 12 个静态文件直接放本目录：

```
NotoSansSC-Regular.ttf   NotoSerifSC-Black.ttf   NotoSerifSC-Bold.ttf
NotoSansJP-Regular.ttf   NotoSerifJP-Black.ttf   NotoSerifJP-Bold.ttf
NotoSansKR-Regular.ttf   NotoSerifKR-Black.ttf   NotoSerifKR-Bold.ttf
NotoSans-Regular.ttf     NotoSerif-Black.ttf     NotoSerif-Bold.ttf
```

也可以一次生成到本目录：

```
python src\tools\font\fetch_noto_fonts.py --fetch --out assets\fonts\noto
```

两条硬规则：

1. **不要放 `-VF.ttf` 可变字体**。脚本按静态文件名取用（`font-map.ini` 里
   映射的也是静态名），VF 需要 fontTools 实例化，交给 fetch 脚本处理。
2. 体积约 96MB，全量入库会让 clone 变慢，所以默认空着、按需下载。

缺失时的行为已经收紧：项目内和系统都没有 → 构建直接失败，不再输出
「字体检查跳过」的包。
