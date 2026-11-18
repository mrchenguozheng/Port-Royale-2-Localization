# 编辑器 HTTP 接口契约（agent 用）

面向需要读写译文、跑校验 / 构建 / 部署的 agent。只描述 `src/editor/server.py`

实际注册的路由（当前 41 条），包括前端自己用的接口。**不是对外网提供的**

**API**，服务只监听本机。

## 启动与连接



```
python src\editor\server.py --port 8777 --no-open
```



* 默认地址 `http://127.0.0.1:8777`，默认端口 `8777`。

* 只允许监听 `127.0.0.1`。接口能直接写仓库文件，不要改成 `0.0.0.0`。

* 没有认证、没有 CORS。token 只用于区分「哪个编辑器实例」，来自环境变量

  `PR2_EDITOR_TOKEN`，默认空字符串；它不是访问凭证。

* 编码一律 UTF-8 JSON。GET 参数放 query；POST 必须发送 JSON **对象**，

  不接受表单、数组或空 body。

* 成功响应的 HTTP 状态是 200；业务失败也可能是 200，要看 `ok` 字段。

* 失败响应统一 `{"detail": "错误说明"}`，状态码为 400 / 404 / 500。

  请求体不是合法 JSON、或不是对象时返回 400。

* 未知路由返回 404 `{"detail": "unknown api: ..."}`；POST 会先解析 body，

  所以 body 非法时先得到 400。

先确认服务和数据根：



```
GET /api/health
→ {"app":"pr2-editor","pid":…,"port":8777,"token":"","started":…,"uptime":…,
   "python":"3.13…","root":"…","dist_mtime":…}
```

`app` 必须是 `pr2-editor`；别的服务占用同一端口时不要继续调用。

## 数据模型

条目 id 是 8 位十六进制 hash，写作 `0xc46f793a`。它是定位一条文本的唯一键，

正文相同的两条也可能有不同 id。

语言代码就是 `src/translations/<code>.toml` 的文件名；基准语言

`en.gog_1.1.2.3` 是英文原文，只读。`GET /api/langs` 返回：



```
{"editable": ["ja", "zh"],
 "all": ["en.gog_1.1.2.3", "fr.gog_1.1.2.42", "ja", "zh"],
 "base": "en.gog_1.1.2.3"}
```

`editable` 里的才能写；`all` 里其他代码是参考语言，写入会被 400 拒绝。

条目行（`/api/list`、`/api/entries`、`/api/search` 返回）的基本形状：



```
{"id":"0xc46f793a","ctx":"","en.gog_1.1.2.3":"Thank you …","zh":"谢谢你 …","ja":"…"}
```

每个语言代码都是行的一个键；`missing` 只在某个参考语言缺这条时出现，

值是缺失语言代码的数组。`ctx` 是数据里的上下文列，通常为空。

列表类接口会截断正文：`/api/list` 截 60 字符，`/api/ids` 的 en 截 80、

译文截 60；`/api/entries` 和 `/api/search` 返回完整正文。

`/api/list` 与 `/api/ids` 的 `zh` 字段名是固定的，值却来自请求里的

`lang`（传 `ja` 时该字段是日文）；不要把它当成语言代码键。

## 写入规则（agent 必须遵守）



1. 只改 `src/translations/<lang>.toml`。每条是 `"0x…" = "译文"`，顺序以

   文件现有顺序为准，**不能重排、不能增删 id**。

2. 写接口是原子写（临时文件 + 替换），并且只更新提交上来的 id；未提交的

   条目原样保留。不要自己用文本编辑器整表覆盖。

3. `POST /api/patch` 保存前会逐条比对英文原文与译文的占位符**数量**

   （`@X$…$`、`%02`、`%2`），不一致整批拒绝，返回 400，错误里最多列 10 条。

   `%02` 与 `%2` 是两个不同 token，不允许归一化。

4. 标签（`<n>`、`<o:…>`、`<t>` 等）由 `/api/check` 报「多 / 少」，但

   `/api/patch` 不拦标签差异；提交前先调用 `/api/check`。

5. 空译文合法，表示游戏里回落到英文；`POST /api/translation` 允许把某条改回空串。

6. 不要用像素宽度或字体宽度判断排版；编辑器只做文本层，实际换行由游戏内

   实测决定。

## 1. 元信息（4 条）



| 方法   | 路径                      | 参数             | 返回                                                       |
| ---- | ----------------------- | -------------- | -------------------------------------------------------- |
| GET  | `/api/health`           | 无              | 见上；含 pid、端口、启动时刻、Python 版本、仓库根、前端产物 mtime                |
| GET  | `/api/server/instances` | 无              | `{"current":端口,"instances":[health…]}`；只扫 8777–8800，可能为空 |
| POST | `/api/server/stop`      | `{"port": 整数}` | `{"ok":bool,"port":int}`；不能停 0 或当前端口                     |
| POST | `/api/shutdown`         | 无              | 先返回 `{"ok":true}`，约 0.2 秒后进程退出                           |

`/api/server/stop` 走目标实例的 `/api/shutdown`，不直接杀进程；端口没在跑

编辑器时返回 `ok:false`。

## 2. 条目读取与校验（14 条）



| 方法   | 路径                   | 参数                                 | 返回                                                      |
| ---- | -------------------- | ---------------------------------- | ------------------------------------------------------- |
| GET  | `/api/context-batch` | `ids`（逗号分隔，最多取前 200 个）、`lang`      | `{id: context}`；不存在的 id 直接省略                            |
| GET  | `/api/rule-trace`    | `id`、`lang`（都必填）                   | `{"id","stages":[{"key","label","text"}]}`；没有该条返回 404   |
| GET  | `/api/translation`          | `id`、`lang`（默认 zh）                 | `{"text": 当前译文}`；文件里没有该 id 返回 404                       |
| GET  | `/api/entry-info`    | `id`、`lang`                        | 占位符 / 标签 / 长度统计，见下；无该条 404                              |
| GET  | `/api/list`          | `lang`                             | 全部条目的短预览 `[{id,en,zh}]`（各 60 字符）                        |
| GET  | `/api/ids`           | `q`、`limit`（默认 20）、`lang`          | `{"ids":[{id,en,zh}],"count":命中总数}`；`q` 按 id 子串匹配       |
| GET  | `/api/find`          | `id`、`lang`                        | `{"id","index","count"}`；index 是文件顺序，找不到为 -1            |
| GET  | `/api/count`         | `filter`（`all`/`attention`）、`lang` | `{"count","ids":[…],"filter","lang"}`                   |
| GET  | `/api/terms`         | `lang`                             | `{"count","issues":{id:[提示…]},"lang"}`；没有术语表时多一个 `note` |
| GET  | `/api/entries`       | `offset`、`limit`、`filter`、`lang`   | 条目行数组；`limit<=0` 返回全部，`offset<0` 按 0                    |
| GET  | `/api/search`        | `q`、`filter`、`lang`                | 条目行数组；空 `q` 返回 `[]`，无分页上限                               |
| POST | `/api/check`         | `{"id","text","lang"}`             | \`\[{level:"error"                                      |
| POST | `/api/translation`          | `{"id","lang","text"}`（`lang` 默认 zh） | `{"ok":true,"text"}`；没有语言文件或无此 id 返回 404                |
| POST | `/api/patch`         | `{"lang","rows":[{"id","text"}]}`  | `{"ok":true,"written":整表条数,"changed":提交条数}`             |

### 细部语义



* `lang` 缺省时，读取类接口用 `editable` 的第一个语言（当前是 `ja`）；

  写入类接口没有默认，必须显式传。

* `filter=attention` 是「占位符 / 标签有问题、空译文、术语不一致」的并集，

  结果按文件顺序；`/api/terms` 只报术语不一致，二者口径不同。

* `context` 形状：



```
{"id":"0x…","category":"界面标签/短标题","reasons":["…"],
 "placeholders":[{"token":"@g$TotalPrice$","meaning":""}],
 "tags":["Line break"],
 "en":"…","zh":"…",
 "neighbors":[{"id":"0x…","en":"…","zh":"…"}]}
```



* `entry-info` 形状：



```
{"placeholders":[{"token":"…","meaning":"…"}],
 "counts":[{"token":"%02","en":1,"zh":2}],
 "mismatch":["%02"],
 "tags":["…"],
 "missing":["原文有、译文没有的 token"],
 "extra":["译文有、原文没有的 token"],
 "used":["译文里出现的 token"],
 "spaces":3,"clean_spaces":3,"extra_spaces":0,
 "length":42,"en_len":57}
```

`missing`/`extra` 按集合算（不管出现次数）；`counts` 才带次数。

`extra_spaces` 恒为 0：引擎补的空格是构建期产物，不在译文层里。



* `rule-trace` 的 `stages` 对 `zh` 是「译文 → 标点规范化 → 连词后空格 →

  人名 / 城镇名空格（补空格前）」四段；其他语言是「译文 → 规范化」两段。

  它只还原译文层，不启动分词器，所以不包含最终的补空格结果。

* `POST /api/check` 的 `text` 是待检查的新文本，不是已保存值；返回的消息

  语言固定为中文（与前端一致）。它不写文件。

* `POST /api/translation` 是**单条、整行替换**，会立刻写盘；适合改回英文或修正

  单条，不适合批量。批量用 `/api/patch`。

* `/api/patch` 的 `written` 是整表最终写出的条数（当前基准 3548），

  `changed` 是提交的 id 数，不代表值真的变了。

## 3. 语言与术语表（7 条）



| 方法   | 路径                         | 参数                                | 返回                                                         |
| ---- | -------------------------- | --------------------------------- | ---------------------------------------------------------- |
| GET  | `/api/langs`               | 无                                 | `{"editable","all","base"}`                                |
| GET  | `/api/lang-summary`        | `lang`（默认 zh）                     | `{"lang","total","todo","done"}`                           |
| GET  | `/api/lang-exists`         | `code`                            | 新建语言的可用性自述，见下                                              |
| GET  | `/api/hash-rules`          | `id`                              | `{"id","rules":{"skip_terms":[…]}}`                        |
| POST | `/api/placeholder-meaning` | `{"lang","id","token","meaning"}` | `{"ok":true,"meanings":{token:含义}}`                        |
| POST | `/api/hash-rule`           | `{"id","term","skip":bool}`       | `{"ok":true,"rules":{…}}`                                  |
| POST | `/api/newlang`             | `{"code","from"}`                 | `{"ok":true,"code","from","aligned","dropped","filled",…}` |



* `lang-summary.todo` 统计「空译文或与英文完全相同」的条数，不是简单的空串数。

* `lang-exists` 的返回可能带 `exists`、`reference`、`path`、`reason`：

  可用时 `ok:true`；代码格式要求「字母开头，字母 / 数字 /`-`/`_`，最长 16」；

  已存在或属于参考语言时 `ok:false`。

* `placeholder-meaning` 写 `glossary/placeholder_meanings.toml`：

  `meaning` 传 `null` 删除该 token 的覆盖，传空字符串则保留空含义。

  缺少 `id` 或 `token` 时返回 200 `{"ok":false,"error":…}`，不写盘。

* `hash-rule` 写 `glossary/hash_rules.toml`；`skip:true` 把术语加入该条的

  `skip_terms`，`false` 移除。缺少 `id`/`term` 返回 `ok:false`。

* `newlang` 以 `from` 为模板整表复制，复制后按基准语言 id 顺序对齐：

  `aligned` 表示模板原本就对齐；`dropped` 是模板多出的 id 数，

  `filled` 是模板缺、用英文补的 id 数。语言代码已存在时返回 400，

  不会覆盖。

* 术语表的 `skip_terms` 只影响 `/api/terms` 与 `attention` 的术语部分，

  不改变占位符 / 标签校验。

## 4. 安装、构建与部署（15 条）



| 方法   | 路径                          | 参数                        | 返回                                                   |
| ---- | --------------------------- | ------------------------- | ---------------------------------------------------- |
| GET  | `/api/start/running`        | 无                         | `{"running":bool,"procs":[{"name","pid"}]}`          |
| GET  | `/api/start/status`         | 无                         | 当前游戏目录状态，见下                                          |
| GET  | `/api/start/dirs`           | 无                         | `{"dirs":[{sha,dir,label,last_used,current,valid}]}` |
| GET  | `/api/start/job`            | 无                         | 后台任务快照 `{running,lines,done,ok,kind,error}`          |
| POST | `/api/start/pick`           | 无                         | 打开系统目录选择框；`{ok,path}` 或 `{ok:false,"error":"已取消"}`   |
| POST | `/api/start/use`            | `{"sha"}`                 | `{"ok":true, …start_status}`                         |
| POST | `/api/start/forget`         | `{"sha"}`                 | `{"ok":true,"dirs":[…]}`                             |
| POST | `/api/start/dir`            | `{"path"}`                | `{"ok":true, …start_status}`                         |
| POST | `/api/start/build-injector` | 无                         | `{"ok":true,"kind":"injector"}`，后台执行                 |
| POST | `/api/start/build`          | `{"langs":["zh",…]}`      | `{"ok":true,"kind":"build"}`，后台执行                    |
| POST | `/api/start/deploy`         | `{"langs":["zh",…]}`（可省略） | `{"ok":true,"kind":"deploy"}`，后台执行                   |
| POST | `/api/start/lang`           | `{"lang"}`                | `{"ok":bool,"lang", …start_status}`                  |
| POST | `/api/start/kill`           | 无                         | `{"ok":bool,"message","procs":[…]}`                  |
| POST | `/api/start/launch`         | `{"lang"?, "vanilla"?}`   | `{"ok":bool,"message":…}`                            |

### 状态形状

`/api/start/status` 未选目录：



```
{"dir":"","valid":false,"langs":["ja","zh"]}
```

选中一个有效游戏目录后追加：



```
{"dir":"…","valid":true,"langs":["ja","zh"],
 "version":"…","sha":"…",
 "patches":[{"name":"…","exists":true}],
 "packs":["zh"],
 "locale":"zh"}
```

`version`、`sha`、`patches`、`packs`、`locale` 只在 `valid:true` 时出现。

### 后台任务

`build-injector` / `build` / `deploy` 只是**启动**任务，立即返回；真正的进度

在 `/api/start/job`：



```
{"running":true,"lines":["…"],"done":false,"ok":false,"kind":"build","error":""}
```

轮询到 `running:false` 才算结束；`done:true` 表示线程收尾，`ok` 表示成功，

`error` 非空表示异常。`lines` 最多保留 500 行。同一时间只允许一个任务，

重复启动返回 `{"ok":false,"error":"已有任务在运行"}`。

### 注意事项



* `/api/start/pick` 会弹 Windows 目录选择框，最长等 180 秒。无人值守的

  agent 不要调用它，直接把已知路径传给 `/api/start/dir`。

* `build` 的 `langs` 必须是 `available_langs()` 的非空子集，否则返回

  `ok:false`；`deploy` 没选语言时部署当前可用语言。

* `deploy`、`start/lang`、`start/launch` 都要求已选有效游戏目录。

* `/api/start/kill` 结束 `PR2.exe` / `PR2Localization.exe`；`launch` 的

  `vanilla:true` 启动无注入的原版。

* 这些接口有真实副作用（写文件、起进程、改 `locale.ini`）。agent 只在

  用户明确要求构建 / 部署 / 启动时调用；不要拿它们做连通性探测。

## 典型 agent 流程

读取并翻译一批：



1. `GET /api/langs` 确认可写语言。

2. `GET /api/count?filter=all&lang=zh` 取 id 顺序；或 `filter=attention`

   只取待处理集合。

3. `GET /api/entries?offset=0&limit=50&filter=all&lang=zh` 取完整正文。

4. 逐条 `POST /api/check`，处理 `error`/`warn`。

5. 把这一批 `{"id","text"}` 放进 `rows`，一次 `POST /api/patch`。

6. `GET /api/entry-info` 或 `GET /api/translation` 抽查写回结果。

只改一条：



```
POST /api/translation
Content-Type: application/json

{"id":"0xc46f793a","lang":"zh","text":"新译文"}
```

批量提交：



```
POST /api/patch
Content-Type: application/json

{"lang":"zh","rows":[{"id":"0xc46f793a","text":"甲"},{"id":"0x384261bc","text":"乙"}]}
```

任何写接口返回 400 时，**不要重试同一批**；先按 `detail` 修正占位符或 id，

再重新校验。