# Noto 源字体（仓库内置）

构建**只认这个目录**。GitHub Actions 不下载字体，也不读 `build/cache/noto-src`、
runner 系统字体；`src/fonts-sources.toml` 里列出的文件缺任何一个，CI 会在构建
注入器之前直接失败。

目录内是 15 个静态文件，约 112MB：

```
简体中文
NotoSansSC-Regular.ttf   NotoSerifSC-Black.ttf   NotoSerifSC-Bold.ttf

繁体中文（台湾／香港共用）
NotoSansTC-Regular.ttf   NotoSerifTC-Black.ttf   NotoSerifTC-Bold.ttf

日语
NotoSansJP-Regular.ttf   NotoSerifJP-Black.ttf   NotoSerifJP-Bold.ttf

韩语
NotoSansKR-Regular.ttf   NotoSerifKR-Black.ttf   NotoSerifKR-Bold.ttf

拉丁／西里尔共用
NotoSans-Regular.ttf     NotoSerif-Black.ttf      NotoSerif-Bold.ttf
```

两条硬规则：

1. **不要放 `-VF.ttf` 可变字体**。`font-map.ini` 映射的是静态文件名；这里的
   15 个文件都是按字重实例化后的静态字体。
2. **换字体必须提交文件**。不要恢复 CI 下载或 `actions/cache`；要更新字体，
   先在本地按 `src/fonts-sources.toml` 生成，再连同 `sha256` 一起提交。

检查：

```
python src\tools\font\fetch_noto_fonts.py --no-system
```

`PR2_FONT_DIRS` 会由 CI/Release 固定指向本目录。缺失时脚本退出 1，并列出
缺的文件。
