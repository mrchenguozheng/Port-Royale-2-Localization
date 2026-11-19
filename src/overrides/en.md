# 英文微调记录

原版提取（`src/orig/en.gog_1.1.2.3.toml`）保持原样，这里只记「为什么和原版不一样」。
判据只有一条：**原版自相矛盾或与玩法不符**，且能拿同族文本互证。不做文风润色。

| id | 原句 | 改句 | 理由 | 依据 |
|---|---|---|---|---|
| `0xf4b68a6b` | … the nation **for which** you want to capture towns must be militarily **weak** and the two nations in question must be at war. | … the nation **for which** you want to capture towns must be militarily **strong** and the two nations in question must be at war. | 同一句前半已经写明「被夺城的国家须军力**弱**」，这一半讲的是「替谁夺城」的国家，须军力**强**，写成 weak 与玩法相反 | 同族结局 `0xf651cc3f`（同一场景失败版）写的是 must be militarily **strong**；两句除成败措辞外整段同构 |

## 复核清单

改过英文的 id，七种语言都要按新句复核一遍：

- `0xf4b68a6b` — ko 已按「强」改（第二批长文里曾照原版译为「약한」）；zh/ja/ru/de/es/fr 待复核。
