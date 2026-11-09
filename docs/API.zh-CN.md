# OpenASRPortal 识别与个人热词 API v1

[English](API.md) | **简体中文**

本文是 OpenASRInput 或其他输入法客户端接入 Portal 的完整下游说明，描述当前实现。
HTTP 和 WebSocket 都属于 v1；不直接连接豆包、百炼或 LocalASR 的内部协议。
管理认证、档案、公共表和用量另见 [管理协议](MANAGEMENT.zh-CN.md)。用户安装与操作见 [使用手册](user-guide.zh-CN.md)。

## 1. 职责、地址与认证

`boson_realtime` 的能力为 `partialResults: false`、`latencyClass: segmented`，不支持 Token 计量和会话热词。音频实时上传，在停顿、达到 15 秒或 `audio.end` 时返回 `transcript.final`。客户端须接受没有前置 partial 的 final；现有 v1 事件结构不变。见 [Boson 行为说明](boson-api-setup.zh-CN.md)。

- 默认 Portal 地址：`http://127.0.0.1:10087`；Input 设置填写 HTTP(S) origin，不带业务路径、查询或用户密码。
- 客户端采集麦克风、重采样、显示波形和预编辑、判断输入目标并提交文字。
- Portal 管理识别会话、上游连接、凭据、个人热词和配额，不操纵 Fcitx 或当前应用。
- 客户端使用 **识别接入 Key**；上游 Key 留在 Portal，管理密码/管理会话不用于识别。
- 所有受保护 HTTP 请求携带 `Authorization: Bearer <ASR_KEY>`；JSON 请求使用 `Content-Type: application/json`。
- WebSocket 用创建会话返回的一次性 ticket 认证，不需要发送长期 Authorization。
- 同 Key 的设备共用个人热词表；每次录音的 sessionId、音频和识别事件独立。不同 Key 隔离。
- Key 撤销后，HTTP 请求返回认证失败，该 Key 的待连接和活动会话也被取消。
- Input 拒绝 HTTP/WS 重定向，并验证 streamPath 指向原 Portal 的当前 session，避免把凭据送到另一地址。
- HTTP 响应使用 `Cache-Control: no-store`；客户端应按需刷新能力、档案、公共目录和个人表。

所有示例 ID、Key、文本及限制说明是示意；运行时以能力与 ready 响应为准。

## 2. 接口总览

| 方法             | 路径                                  | 认证与用途                          |
| ---------------- | ------------------------------------- | ----------------------------------- |
| GET              | `/health`                             | 无认证，存活检查                    |
| GET              | `/v1/capabilities`                    | ASR Key，协议与音频能力             |
| GET              | `/v1/profiles`                        | ASR Key，脱敏识别档案与默认选择     |
| POST             | `/v1/sessions`                        | ASR Key，创建一轮会话               |
| WS               | `/v1/sessions/{id}/stream?ticket=...` | 单次 ticket，上传音频和接收事件     |
| DELETE           | `/v1/sessions/{id}`                   | ASR Key，取消自己的会话             |
| GET/PATCH        | `/v1/hotwords`                        | ASR Key，读取/保存个人表            |
| DELETE           | `/v1/hotwords/statistics`             | ASR Key，清空自己的词频统计         |
| GET              | `/v1/hotwords/catalog`                | ASR Key，共享推荐目录               |
| GET              | `/v1/hotwords/catalog/{sourceId}`     | ASR Key，下载完整公共推荐正文       |
| POST             | `/v1/hotwords/dictionaries`           | ASR Key，预览词表或保存个人推荐快照 |
| GET/PATCH/DELETE | `/v1/hotwords/dictionaries/{id}`      | ASR Key，管理自己的推荐快照         |

公共目录是有效 Key 共用的推荐内容；个人表与个人快照只有相应 Key 可读写。
公共管理路径 `/v1/admin/hotwords/public-dictionaries` 需要管理身份，识别客户端不能调用。

## 3. 能力与档案

### 3.1 GET /health

```json
{ "status": "ok", "service": "OpenASRPortal", "protocolVersion": 1, "managementPage": "/admin" }
```

健康响应不代表已配置上游、不代表某个 Key 还有配额，也不创建录音会话。

### 3.2 GET /v1/capabilities

```json
{
  "protocolVersion": 1,
  "audio": { "encoding": "pcm_s16le", "sampleRate": 16000, "channels": 1 },
  "maxSessions": 8,
  "maxRecordingMs": 300000,
  "resumable": false,
  "hotwords": {
    "version": 1,
    "path": "/v1/hotwords",
    "scope": "access-key",
    "dictionaries": true,
    "catalogPath": "/v1/hotwords/catalog",
    "personalTableOnly": true,
    "recommendationWords": true,
    "publicDictionaries": true,
    "publicDownloadPath": "/v1/hotwords/catalog/{sourceId}"
  },
  "events": [
    "session.ready",
    "transcript.partial",
    "transcript.final",
    "session.finished",
    "session.cancelled",
    "session.error"
  ]
}
```

`maxSessions` 默认 8，是整个 Portal 的容量，并非每 Key 8 个；服务构造参数可以修改。
v1 不支持音频续传。较旧 Portal 可能没有公共下载或个人表限定能力字段；读取时允许缺失新增字段。
Input 在不支持热词 v1 时提示升级。新客户端可用 `publicDictionaries` 判断是否支持独立公共下载接口，
也可使用兼容的 `POST dictionaries` + `sourceId/preview:true` 下载推荐。

### 3.3 GET /v1/profiles

返回 `profiles`、`defaultProfileId` 和管理员设置的 `profileOrder`。
`profiles` 按管理员顺序列出档案，可能包含停用档案，应结合 `quota` 展示可用状态。

```json
{
  "profiles": [
    {
      "id": "doubao-1",
      "title": "默认云端识别",
      "provider": "doubao_realtime",
      "configuration": { "endpoint": "wss://example.invalid/asr", "hasApiKey": true },
      "quota": { "enabled": true, "disabledReason": "", "exhausted": false, "tokenBlocked": false },
      "capabilities": {
        "partialResults": true,
        "textProcessing": "native",
        "latencyClass": "streaming",
        "audio": { "encoding": "pcm_s16le", "sampleRate": 16000, "channels": 1 },
        "tokenUsage": false,
        "hotwords": { "supported": true, "mode": "inline-context", "maxTokens": 100 }
      }
    }
  ],
  "defaultProfileId": "doubao-1",
  "profileOrder": ["doubao-1"]
}
```

`configuration` 的其他字段随 provider 变化，密钥不回显。`quota` 也可能为 null。
`profileId` 是 Portal 档案 ID，不是模型名称；客户端不直接通过创建会话切换上游模型。
`latencyClass=streaming` 表示流式，`segmented` 表示分段/轮询式预览，不承诺同样延迟。

## 4. 创建会话与一次性连接

### 4.1 POST /v1/sessions

```json
{
  "profileId": "doubao-1",
  "clientRequestId": "f22b73e4-9c6d-4b29-82a6-example",
  "purpose": "dictation",
  "audio": { "encoding": "pcm_s16le", "sampleRate": 16000, "channels": 1 }
}
```

| 字段            | 规则                                                          |
| --------------- | ------------------------------------------------------------- |
| profileId       | 可省略、null 或空字符串，此时跟随默认；非空须为合法 ID 且存在 |
| clientRequestId | 可省略；文本，最多 200 字符；推荐每轮一个 UUID                |
| purpose         | 当前 Input 固定发送 dictation；描述用途，不另授权限           |
| audio           | 可省略；填写时必须与协商的 PCM16 / 16 kHz / 单声道完全相同    |

非空 profileId 的格式为 `[A-Za-z0-9][A-Za-z0-9_.-]{0,99}`。
显式选择不存在或停用的档案时不会偷偷切换到其他档案。
默认档案在创建时解析并固定，包括上游配置和该 Key 的个人热词选择。

成功状态 **201**：

```json
{
  "sessionId": "session-example",
  "ticket": "one-time-ticket-example",
  "streamPath": "/v1/sessions/session-example/stream",
  "ticketExpiresInMs": 29999
}
```

ticket 默认 30 秒有效，单次使用。返回 TTL 是剩余毫秒；不要把示例值写死。
Input 校验 streamPath 恰为当前 session 的同源路径，再连接原 Portal 的 WS/WSS 地址。

**创建重试的幂等范围**：同 Key、同非空 clientRequestId、尚未连接且未过期时返回同一描述，
不会延长 ticket 期限；已建立 WS 返回 409 `SESSION_STARTED`。
会话结束或过期清理后，不再保证同请求 ID 返回旧会话，因此不能用它重放已识别音频。

### 4.2 WebSocket 握手

连接地址：

```text
ws://127.0.0.1:10087/v1/sessions/session-example/stream?ticket=one-time-ticket-example
```

HTTPS Portal 使用 WSS。HTTP 升级成功后上游建立连接，客户端等待 `session.ready`。
准备失败可能在升级前返回 HTTP 错误，也可能升级后收到 `session.error`；不能假定首条必定成功。
ticket 已使用、会话不存在或 Key 已撤销，握手返回 401 `AUTH_FAILED`。
尚可定位到过期票据时返回 401 `TICKET_EXPIRED`；已清理后可能只返回 `AUTH_FAILED`。
失败后创建新会话，旧 ticket 不能续传或复用。

## 5. 音频与客户端控制

### 5.1 二进制音频

- 等待 ready 后发送 **WebSocket binary message**；音频不是 JSON、Base64 或文件上传。
- 有符号 16 位小端 PCM，采样率 16000 Hz，单声道；不带 WAV/MP3 文件头。
- 每个块字节数为偶数；Input 发送的块非空，每个 16 位样本完整。
- 20 ms 音频为 640 字节，200 ms 为 6400 字节；服务端内部按 6400 字节批量发送上游。
- 上游双向流动期间持续读取事件，不能等上传全部结束才开始接收。
- 单条 WS 消息最大 1 MiB；最大录音 300 秒，音频总量上限 9600000 字节。
- Input 当前在约 295 秒主动收尾，为服务端五分钟限制留出余量。
- Portal 使用 WS heartbeat 30 秒；不是自定义业务 `ping` 控制消息。

### 5.2 正常收尾

发送一次文本 JSON：

```json
{ "type": "audio.end" }
```

发送后停止上传音频，但继续接收 partial/final，直至 `session.finished` 或失败终态。
`audio.end` 会把尚未凑满批次的 PCM 一起 flush；不要用关闭 socket 代替收尾。
Input 按 ready 返回的 finalizeTimeoutMs 设置一次性的收尾截止时间，新 partial 不延长截止时间。

### 5.3 取消

WS 已建立时可发送：

```json
{ "type": "session.cancel" }
```

还未连接、正在连接或需要显式清理时，使用带 ASR Key 的：

```text
DELETE /v1/sessions/{sessionId}
```

成功返回 `{"ok":true}`。取消不存在/已清理会话也返回成功；仍存在但属于其他 Key 时返回 403。
同 Key 可以取消自己的任意会话；客户端应只取消自己创建的 sessionId。
取消是放弃本轮，区别于等待定稿的 audio.end；不能把 session.cancelled 当作成功 finished。

## 6. 服务端事件与结果账本

### 6.1 公共字段

每条事件包含 `type`、`sessionId`、`seq`。seq 为从 1 开始的会话内递增整数。
在正常连接内按发送顺序连续；客户端首先拒绝旧 sessionId，再验证 seq。
已处理的 seq 可以忽略；新 seq 出现缺口应视为协议故障，不能自行补交旧音频。
同一文本即使未改变，也可能对应新 seq；应更新事件序号账本，不能只按文本去重。

### 6.2 session.ready

```json
{
  "type": "session.ready",
  "sessionId": "session-example",
  "seq": 1,
  "audio": { "encoding": "pcm_s16le", "sampleRate": 16000, "channels": 1 },
  "textProcessing": "native",
  "finalizeTimeoutMs": 11000,
  "hotwords": { "supported": true, "appliedCount": 2, "omittedCount": 0 }
}
```

ready 每个会话一次；验证 audio 与预期一致、finalizeTimeoutMs 为正整数。
超时值取决于实际 provider。hotwords 是创建时的快照计数，不是整张个人表。
`supported=true` 不等于热词已开启；默认关闭时 appliedCount 为 0。

### 6.3 transcript.partial 与 transcript.final

```json
{
  "type": "transcript.partial",
  "sessionId": "session-example",
  "seq": 2,
  "utteranceId": "session-example:1",
  "revision": 1,
  "text": "神经网",
  "startMs": 0,
  "endMs": 800,
  "source": ""
}
```

```json
{
  "type": "transcript.final",
  "sessionId": "session-example",
  "seq": 3,
  "utteranceId": "session-example:1",
  "revision": 2,
  "text": "神经网络。",
  "startMs": 0,
  "endMs": 1100,
  "source": ""
}
```

| 字段          | 含义                                              |
| ------------- | ------------------------------------------------- |
| utteranceId   | 当前语句稳定标识；客户端应视为不透明字符串        |
| revision      | 本语句递增修订号，正整数；新语句重新计数          |
| text          | 完整替换文本，不是相对上一版的增量；可为空字符串  |
| startMs/endMs | 相对于本会话音频的时间，未知或无有效区间时为 null |
| source        | 上游提供的来源说明，可为空；不能用它作为去重键    |

partial 更新当前语句的预编辑，后来的更高 revision 替换早先版本。
final 终结这一语句，之后不再允许改写已定稿正文；下一语句有新的 utteranceId。
忽略旧 revision，但仍消费对应的新 seq。重复 final 不重复提交；final 正文被改写视为协议错误。
空 final 也计入 finalCount，尽管没有字符需要上屏。所有 provider 的最终结果使用相同字段。

### 6.4 成功、取消和错误终态

```json
{ "type": "session.finished", "sessionId": "session-example", "seq": 4, "finalCount": 1 }
```

`finalCount` 必须等于客户端收到的唯一 final 数量。Input 还要求不存在未定稿的非空 preview。
只收到 socket 关闭但没收到终态，不能认为录音成功。

配额用尽导致自动收尾时：

```json
{
  "type": "session.finished",
  "sessionId": "session-example",
  "seq": 4,
  "finalCount": 1,
  "reason": "quota_exhausted",
  "quotaScope": "key"
}
```

quotaScope 取决于触发阶段，可能是 key/profile/account；把它作为诊断信息，不拼装新的输入指令。
该终态之前的稳定 final 仍有效；停止采集，不继续向该 socket 发送音频。

```json
{ "type": "session.cancelled", "sessionId": "session-example", "seq": 4 }
```

```json
{
  "type": "session.error",
  "sessionId": "session-example",
  "seq": 4,
  "code": "FINALIZATION_TIMEOUT",
  "message": "等待最终定稿超时",
  "retryable": true,
  "requestId": "diagnostic-request-id"
}
```

终态之后不再更新账本。错误不会再附带成功 finished。
retryable 表示可尝试新会话，不授权自动重放音频，也不能保证重试立即成功。

## 7. 输入法客户端的本地状态与提交

推荐生命周期：

```text
idle/paused → connecting → session.ready → listening
listening → 停止并 flush → audio.end → pausing → session.finished → paused
任意活动状态 → cancel → session.cancelled → idle
连接/识别/提交故障 → failed
```

暂停不是一条 WS pause 指令：Input 收尾本会话，恢复录音时创建新的会话。
Input 使用 Shift+Space 启停普通听写，Enter 收尾、Esc 取消；文本指令修改默认 Linux Alt+Z、Windows Alt+X。这些按键不传给 Portal。

当前 Input 按 final 逐句放入提交队列，在宿主安全事件循环调用桥接；不等待整个会话结束才显示所有文字。
其他客户端可以等 finished 后统一提交，但两种策略都必须保证每个 final 最多提交一次。
partial 不可当作永久文字。Portal 的 utteranceId/revision 是识别去重，宿主 commitId 是本地提交去重，两者职责不同。

Input 为目标保留 `lease/contextId/focusEpoch`，用 `generation` 区分本地录音轮次。
上述字段属于本地桥接，不是 Portal HTTP/WS 字段。失焦、目标切换、旧 generation 或旧 session 的事件
不得进入新的输入框；提交 ACK 不明确时保留未确认文本，不凭空重发到新目标。
已成功上屏的文字不会因之后取消而被 Portal 自动撤回。

## 8. 个人热词表与公共推荐

### 8.1 GET /v1/hotwords

可带 `?profileId=...` 查看指定档案的选词能力；不带则使用默认。
无默认上游时仍能管理个人表，selection 缺省；指定不存在档案返回 404。

```json
{
  "version": 1,
  "revision": 0,
  "profileId": "doubao-1",
  "settings": {
    "enabled": false,
    "autoLearn": false,
    "windowDays": 30,
    "minFrequency": 3,
    "maxWords": 100,
    "manualTerms": [],
    "excludedTerms": []
  },
  "learnedTerms": [],
  "terms": [],
  "dictionaries": [],
  "dictionaryCandidateLimit": 0,
  "personalTableOnly": true
}
```

若有 selection，还包含 capability、terms、omitted、appliedCount、budgetUsed。
terms 是已保存且没有被排除的个人词；selection.terms 是当前上游真正将收到的子集。
manualTerms 为历史字段名，对应用户真正维护的“我的热词表”。
新版 Input/Portal 页面以逐行表格展示词语、权重和启用状态；停用词保留在 manualTerms，
同时加入 excludedTerms。页面保存使用 autoLearn=false、maxWords=2000；个人 JSON 下载/导入格式见
下方“个人表文件格式”。

| 设置          | 默认/限制                                               |
| ------------- | ------------------------------------------------------- |
| enabled       | false；总开关，必须显式开启并保存                       |
| autoLearn     | false；仅统计稳定定稿词频，不自动向个人表加词           |
| windowDays    | 30，整数 1–90                                           |
| minFrequency  | 3，整数 2–100，兼容词频统计参数；新版页面不展示词频推荐 |
| maxWords      | 100，整数 1–2000，每轮选用上限                          |
| manualTerms   | 最多 2000 项，每项 text、weight；权重整数 1–5，省略时 4 |
| excludedTerms | 最多 2000 项，排除词字符串列表                          |

词语 NFKC 规范化、合并空白，长度 2–64；允许文字/数字/空格及 `. + # - / _ '`，
不接受纯符号；个人词按忽略大小写检查重复。排除列表优先，不自动恢复已删除词。

### 8.2 PATCH /v1/hotwords

```json
{
  "revision": 0,
  "settings": { "enabled": true, "manualTerms": [{ "text": "神经网络", "weight": 4 }] }
}
```

settings 可以部分更新；数组字段整体替换。必须携带最近查询的整数 revision。
同 Key 的其他设备保存后 revision 已变，旧编辑返回 409 `HOTWORDS_CONFLICT`，需刷新后重新编辑。
成功返回完整最新个人数据。新增、删除或修改只影响之后创建的会话，不能改写活动会话快照。

`learnedTerms` 提供 text/frequency/lastSeen/excluded 词频推荐。自动统计仅从启用之后的稳定 final 累计，
不保存完整音频或全文，不从 partial 学习。`DELETE /v1/hotwords/statistics` 返回 `{"ok":true}`，
清空词频但保留个人表、排除词和去重 ID；之后 GET 再刷新界面。

### 8.3 公共目录、下载与逐词选择

`GET /v1/hotwords/catalog` 返回：

```json
{
  "formats": ["auto", "text", "tsv", "csv", "json", "rime"],
  "maxBytes": 4194304,
  "maxWords": 50000,
  "maxDictionaries": 8,
  "recommendationOnly": true,
  "sources": [
    {
      "id": "tech-ai",
      "title": "AI 入门词库",
      "description": "领域术语",
      "license": "项目维护的术语列表",
      "homepage": "",
      "format": "text",
      "url": "",
      "kind": "portal-public",
      "revision": 1,
      "wordCount": 40,
      "downloadPath": "/v1/hotwords/catalog/tech-ai"
    }
  ]
}
```

kind 为 portal-public 时，内容是 Portal 管理员发布的持久表；external 是项目预置的联网来源入口。
sources 的数量、名称及 ID 可变，不应写死或缓存到无法刷新；不是每张表都包含相同摘要字段。

`GET /v1/hotwords/catalog/{sourceId}` 返回完整 `format/words/report/source/recommendationOnly`。
words 项含 text、weight、frequency、position；source 记录来源及 sha256，Portal 公共表还含当前 revision。
report 包含 rows/wordCount/skipped/duplicates/warnings/sample（最多 20 个样例）。
未发布或已删除公共表返回 404 `PUBLIC_DICTIONARY_NOT_FOUND`；联网来源可能返回 502。

兼容下载方式：

`POST /v1/hotwords/dictionaries`：

```json
{ "sourceId": "tech-ai", "preview": true }
```

该预览同样返回完整 words；不修改个人表、不保存快照、不增加个人 revision。
客户端把下载列表展示给用户，逐词启用加入本地个人表编辑；删除/调整后，经用户保存 PATCH 上传。
**下载整表不是启用整表。公共表更新或删除不改变已有个人词；只有保存的个人表用于识别。**

### 8.4 文件预览与个人推荐快照

```json
{ "preview": true, "format": "text", "content": "神经网络|4\n医学成像|3\n" }
```

通过 POST dictionaries 可预览 TXT/TSV/CSV/JSON/RIME；最多 4 MiB、50000 有效词。
不执行 RIME 配置或自动展开 import_tables。此接口不是 PDF/整篇文章关键词分析接口。

去掉 preview 并提供 `revision`、`title` 时保存一份**个人推荐快照**，返回 201，
附 importedDictionaryId 和 importReport；最多 8 份/Key。
`GET dictionaries/{id}` 读取完整 words；PATCH 使用 `{"revision":n,"patch":{"title":"新名称"}}`，
DELETE 使用 `{"revision":n}`。这些写入也增加该 Key 个人 revision。
兼容 PATCH 的 enabled 字段仍接受，但快照的启用状态不决定真正识别词。
删除快照不会删除已经选入个人表的词。读取/改动其他 Key 的快照返回 404。

### 8.5 上游限制

- 豆包双向流式当前限 100 tokens；Portal 保守按 UTF-8 字节预算过滤，不等于 100 个词。
  过滤超过 9 字符、数字或不支持符号的词；该接口不发送通用 weight。
- 百炼当前模型最多 2000 个即时词；非 ASCII 词最多 15 字符，ASCII 词组最多 7 个空格分段。
- 当前 LocalASR 协议没有会话级热词入口，supported=false；仍能管理个人表。
- omitted.reason：disabled、unsupported、count-limit、term-format、token-budget。
  客户端应显示原因，不应私自修改全局模型词表或绕过上游限制。

## 9. HTTP 错误与恢复

统一业务 HTTP 错误体：

```json
{
  "error": { "code": "AUTH_FAILED", "message": "Portal 接入凭据无效", "requestId": "diagnostic-id" }
}
```

| HTTP | 常见 code                                                              | 客户端处理                                   |
| ---- | ---------------------------------------------------------------------- | -------------------------------------------- |
| 400  | INVALID_REQUEST / INVALID_PROFILE / UNSUPPORTED_AUDIO                  | 修正 JSON、ID 或音频，不反复发送同样错误请求 |
| 401  | AUTH_FAILED / TICKET_EXPIRED                                           | 检查 Key；过期连接需新建会话                 |
| 402  | QUOTA_EXHAUSTED                                                        | 停止识别，提示管理员补充额度                 |
| 403  | AUTH_FAILED                                                            | 当前 Key 无权取消该已存在会话                |
| 404  | PROFILE_NOT_FOUND / DICTIONARY_NOT_FOUND / PUBLIC_DICTIONARY_NOT_FOUND | 刷新档案/目录，保留用户未保存编辑            |
| 409  | SESSION_STARTED                                                        | 不重复建立同一录音的 WS                      |
| 409  | HOTWORDS_CONFLICT                                                      | 刷新个人表，处理另一设备的编辑               |
| 409  | PROFILE_DISABLED / TOKEN_USAGE_UNSUPPORTED / TOKEN_USAGE_UNAVAILABLE   | 调整选择或由管理员处理                       |
| 429  | UPSTREAM_BUSY                                                          | Portal 容量不足，稍后新建会话                |
| 502  | DICTIONARY_DOWNLOAD_FAILED                                             | 联网词表下载失败，可手动下载文件后预览       |
| 503  | NO_UPSTREAM_AVAILABLE                                                  | 所有默认候选上游不可用，等待管理员恢复       |

WS 阶段错误通过 session.error 报告，例如 AUDIO_LIMIT、SESSION_TIMEOUT、FINALIZATION_TIMEOUT、
UPSTREAM_CLOSED、CLIENT_DISCONNECTED、UPSTREAM_ERROR；部分解析/上游异常合并为 UPSTREAM_ERROR。
先停止采集和上传，清除本轮预编辑，保留未确认文字。新录音使用新 generation、sessionId 和 ticket。
提供 requestId 可协助定位错误；错误码比中文 message 更适合程序分支。

## 10. 最小调用顺序与 HTTP 示例

1. GET capabilities 验证 v1/audio，GET profiles 选择显式档案或默认。
2. 为当前输入目标取得本地 lease，生成本轮 clientRequestId。
3. POST sessions，验证 sessionId、streamPath、ticket TTL。
4. 连接同源 WS/WSS，接收并验证 ready。
5. 启动 PCM 采集；上传与事件接收并发；partial 替换预编辑，final 去重后提交。
6. 停止录音并 flush，发送 audio.end，继续等最终事件。
7. finished 核对 finalCount；清理本轮 socket 和桥接预编辑。
8. 取消/故障/失焦只清理本轮；新的目标、新的录音建立新会话。

```bash
# ASR_KEY 是管理员提供的识别接入 Key；PORTAL 为你的服务地址。
PORTAL=http://127.0.0.1:10087
curl -H "Authorization: Bearer $ASR_KEY" "$PORTAL/v1/capabilities"
curl -H "Authorization: Bearer $ASR_KEY" "$PORTAL/v1/profiles"
curl -X POST -H "Authorization: Bearer $ASR_KEY" -H 'Content-Type: application/json' \
  -d '{"purpose":"dictation","audio":{"encoding":"pcm_s16le","sampleRate":16000,"channels":1}}' \
  "$PORTAL/v1/sessions"
curl -H "Authorization: Bearer $ASR_KEY" "$PORTAL/v1/hotwords/catalog"
curl -H "Authorization: Bearer $ASR_KEY" "$PORTAL/v1/hotwords/catalog/tech-ai"
```

最后一个示例以管理员仍保留并发布 tech-ai 为前提，实际应先读取目录。
公开 HTTP/WS 集成不需要导入 Portal 的 Python 源码；Input 客户端实现参考其自有
`adapters/portal.py`、`domain/ledger.py` 和 `application/controller.py`。
Portal 的源码回归、Input 黑盒契约及真实双页面词库测试见 [测试约束](testing.zh-CN.md)。

## 11. 个人表文件格式与推荐文件

Input 和 Portal 的个人表编辑器导出以下 JSON，也可导入 terms 数组：

```json
{
  "format": "OpenASRPortal.PersonalHotwords",
  "version": 1,
  "terms": [
    { "text": "机器学习", "weight": 4, "enabled": true },
    { "text": "Node.js", "weight": 3, "enabled": false }
  ]
}
```

文件不含 Key、连接和总开关；下载的是当前编辑内容。导入按 NFKC、忽略大小写合并，同名词采用导入权重/状态；无效词、文件内部重复、超过 4 MiB 或合并超过 2000 词时整次失败。导入后仍须保存，线上以 manualTerms/excludedTerms 表示完整表和停用项。

公共/推荐文件解析支持 UTF-8（含 BOM）：TXT 每行一词或 `词语|权重`；TSV 词语/词频或 RIME 词语/编码/词频；CSV text/frequency/weight；JSON 字符串数组、词对象数组、vocabulary 对象或词到权重映射；RIME 支持默认列及 columns 元信息。频率仅排序，不作 ASR 权重，缺省权重 4。技术符号仍须经过目标上游限制。

RIME 不执行 Lua、YAML 对象标签或 import_tables，也不读取二进制数据库、.bin/.scel。导入报告保留引用提示，使用者需获取实际正文文件。单文件 4 MiB / 50000 词，个人快照最多 8 份；完整推荐不占用个人表 2000 词额度，逐词加入才占用。

## 12. 可选词频学习与提供商映射

autoLearn 只统计启用后的去重稳定 final；partial、重复 final、管理静音探测不计数。已发出的 final 即使会话后来取消也保留统计。Jieba 分词过滤单字、纯数字和常见停用词，英文统一小写；不做实体识别或专有名词自动纠错。仅保留词、UTC 日计数、最近时间和去重 ID，不保存全文/录音。

windowDays 包含当前 UTC 日，最多 90 天；每 Key 每日最多 5000 种词，查询展示前 2000 种，超量按词频和最近时间淘汰。关闭学习保留历史，统计失败不打断识别，清空统计保留个人表和去重 ID。统计和公共推荐永远不自动并入个人表。

豆包当前双向流式通过 request.corpus.context 发送序列化 `{"hotwords":[{"word":"麒麟"}]}`，不是 nostream 的 5000 词接口；100 tokens 用保守 UTF-8 字节预算近似，不能当精确 tokenizer 或 100 个词，不传通用 weight。百炼 `qwen-audio-3.1-asr-flash-streaming` 通过 run-task parameters.vocabulary 发送词到 1–5 权重映射。Soniox `stt-rt-v6` 发送不带权重的 context.terms，保守限制为 7000 UTF-8 字节。LocalASR 当前不发送热词参数。百炼和 Soniox 均暴露 `partialResults: true`、`latencyClass: streaming`；仅百炼支持计费 Token 用量。

提供商依据：[豆包流式接口](https://www.volcengine.com/docs/6561/1354869)、[热词规范](https://docs.volcengine.com/docs/DoubaoVoice/Hotwords?lang=zh)、[百炼热词说明](https://help.aliyun.com/zh/model-studio/improve-asr-accuracy)。实际增强效果需真实账号和音频验证，模拟载荷检查不能代替识别质量测试。
