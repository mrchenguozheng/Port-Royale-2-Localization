# 游戏原版字体备份

`original/` 是游戏自带四个拉丁字体的备份（不进 git，游戏资源）。

## 来源与校验

从四个版本的 `pr2_loca.cpr` 分别导出，结果完全一致：

| 文件 | 大小 | SHA-256（前 12 位） |
|---|---:|---|
| `ARIAL.TTF` | 296,712 | `1906A771ED87` |
| `ELGRECO_.TTF` | 65,680 | `F3715E590517` |
| `Tiepolo_black.ttf` | 52,876 | `267F1A2DE1C1` |
| `Tiepolo_bold.ttf` | 53,120 | `FD10E52DD504` |

验证过的版本：

- GOG 英文 `1.1.2.3`
- GOG 法文 `1.1.2.42`
- GOG 旧版目录
- Steam 英文

## 重新导出

```bash
python src/tools/font/extract_fonts.py --game-dir "<游戏目录>" --out assets/fonts/original
```

即使 `fonts/` 已经被替换过，原版仍在 `pr2_loca.cpr` 里，随时可以恢复。

## 注意

`fonts/_orig_bak` 里通常不是游戏原版，而是之前换上的中文字体；
不要把那份当成原版备份。
