# Port Royale 2 Localization

《Port Royale 2》的本地化项目：**用外挂语言包替换界面文本，原版 `PR2.exe` 全程不改。**

Steam 版 `PR2.exe` 带 Valve CEG 完整性校验，改 exe 哪怕一个字节都会
启动即报 `Application load error 3:0000065432`。所以走运行时注入：
启动器把 DLL 注入游戏进程，DLL 接管引擎的取字调用，把语言包里的译文送进去。

---

## 快速开始

需要 Visual Studio（C++ 桌面开发组件）+ Python 3.11 且带 tkinter。

```
src\build_n_patch.bat
```

选游戏目录、勾选语言、构建、安装，然后用游戏目录里的
`PR2Launcher.exe` 启动（**不要直接跑 `PR2.exe`**，那样不会加载语言包）。

五个按钮各管一件事，构建与安装的细节见[构建与安装](docs/构建与安装.md)。

---

## 仓库结构

```
Port Royale 2 Localization/
├─ src/
│  ├─ translations/         译文人工维护源（唯一）
│  │  ├─ zh.toml
│  │  └─ references/        en.toml / fr.toml，只读参考原文
│  ├─ injector/             注入组件源码（纯 C++）
│  ├─ tools/                语言包与译文处理脚本（Python）
│  ├─ build_n_patch.bat     日常入口
│  └─ locale.ini            语言选择模板
├─ build/                   产物，可整个删掉重建
├─ docs/
└─ README.md
```

| 文件 | 角色 |
|---|---|
| `PR2Launcher.exe` | 启动器。挂起方式启动 `PR2.exe`，注入 DLL 后恢复执行 |
| `PR2TextSource.dll` | 主逻辑。hook 引擎取字的三条路径，把译文替换进去 |
| `PR2Packs\` | 语言包目录。`<语言>.txt` + `locale.ini`，可直接改文本 |

---

## 加一种语言

三步，不需要碰 C++：

1. `python src\tools\new_lang.py --new-lang <代码>`
   —— 复制一份 `references\en.toml` 为 `translations\<代码>.toml`
2. 逐条把每行右边的英文改成译文（没改的会显示英文），
   然后跑 `src\build_n_patch.bat`，勾选新语言 → 构建 → 安装
3. 改 `PR2Packs\locale.ini` 的 `language=`，重启游戏

条目不必写全 —— 没写的自动显示英文。详细说明见
[译文与语言包](docs/译文与语言包.md#加一种语言)。

---

## 文档

| 文档 | 内容 |
|---|---|
| [构建与安装](docs/构建与安装.md) | 窗口按钮、单独构建、脚本一览 |
| [注入组件](docs/注入组件.md) | 运行时原理、hook 三条路径、源码职责、编译 |
| [译文与语言包](docs/译文与语言包.md) | toml 格式、校验规则、加一种语言 |

---

## 已知限制

- **hook 目标与游戏版本绑定。** 代码按固定偏移取 `A2dLib-2.20A.dll`
  的函数，换游戏版本可能需要改偏移，否则整体不生效。
- **中文条目整条不显示是分词问题，不是标签问题。** 引擎按空格切词，
  整串汉字超宽会被整条丢弃，只能逐条在游戏里实测。
- 加载失败静默无日志。现象是显示英文界面，但无从判断是补丁没跑
  还是语言包没找到。

---

## 许可

见 [LICENSE](LICENSE)。
