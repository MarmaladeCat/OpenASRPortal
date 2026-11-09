# OpenASRPortal.Management v1

[English](MANAGEMENT.md) | **简体中文**

这是网页、OpenNotes、OpenDrafts 共同使用的公开管理协议，不是共享代码包。
HTTP JSON，管理请求携带 `Authorization: Bearer <管理会话令牌>`，不是明文管理密码。
首次设置和登录见下文；密码/Key 由数据库管理，不使用凭据环境变量。
所有配置读取都脱敏，上游 Key 仅保留在 Portal。

提供商 `boson_realtime` 暴露 `apiKey`、固定 `endpoint`（`wss://api.boson.ai/v1/realtime`）、固定 `model`（`higgs-stt-3.1`）、`language`（`auto` 或两位小写语言代码）和整数 `silenceMs`（600–3000，默认 800）。支持时长额度，不支持 Token 额度和会话热词。见[开通配置](boson-api-setup.zh-CN.md)。

## 接口

| 方法      | 路径                            | 语义                                               |
| --------- | ------------------------------- | -------------------------------------------------- |
| GET       | /v1/admin/contract              | protocol / version / providers 的表单与字段契约    |
| GET       | /v1/admin/profiles              | 全部 profiles、defaultProfileId、managementVersion |
| POST      | /v1/admin/profiles              | 增加配置，id 重复返回 409                          |
| GET       | /v1/admin/profiles/{id}         | 查看单个配置                                       |
| PATCH     | /v1/admin/profiles/{id}         | 修改现有配置，不存在返回 404                       |
| PUT       | /v1/admin/profiles/{id}         | 幂等保存指定 id，便于部署注册                      |
| DELETE    | /v1/admin/profiles/{id}         | 删除配置；重复删除幂等                             |
| POST      | /v1/admin/profiles/{id}/test    | 测试保存配置或请求体中的草稿，不持久化             |
| POST      | /v1/admin/proxy/test           | 仅管理员可用的代理可用性与请求耗时测试             |
| GET/PATCH | /v1/admin/settings              | 查看/设置 defaultProfileId                         |
| GET/POST  | /v1/admin/asr-keys              | 读取脱敏 Key 列表 / 派生命名的 ASR Key             |
| DELETE    | /v1/admin/asr-keys/{id}         | 永久撤销该 Key，取消它的识别会话                   |
| GET       | /v1/admin/asr-keys/{id}/secret  | 仅管理权限按需查看可解密的完整客户端 Key           |
| POST      | /v1/admin/asr-keys/{id}/recover | 以匹配的原值恢复旧版哈希记录的查看能力             |
| GET       | /v1/admin/usage                 | 按时间查询下游 Key 和上游的时长、Token、请求统计   |
| PATCH     | /v1/admin/asr-keys/{id}/quota   | 修改下游 Key 的剩余秒数和剩余 Token                |
| PATCH     | /v1/admin/profiles/{id}/quota   | 修改上游剩余额度、启用/停用状态                    |

新增/修改体：

```json
{
  "id": "my-asr",
  "title": "我的语音服务",
  "provider": "openlocalasr",
  "configuration": {
    "endpoint": "ws://127.0.0.1:10095/api-ws/v1/inference",
    "model": "funasr_sensevoice_small",
    "apiKey": "服务端 Key"
  }
}
```

id 为不可变标识，允许字母/数字及下划线、短横线、点，长度不超过 100。
provider 和 endpoint 不要求唯一；同一端点的多个账号以不同 id 保存，各自拥有独立 Key 和配额。
新增配置必须显式提供 apiKey，不从其他配置继承。
修改时省略 apiKey 保留同 provider 的原 Key；更换 provider 不复用旧提供商 Key。
读取 configuration.hasApiKey 表示是否保存，不返回明文。

## 描述契约

GET contract 返回：

```json
{
  "protocol": "OpenASRPortal.Management",
  "version": 1,
  "providers": [
    {
      "id": "openlocalasr",
      "title": "OpenLocalASR · 本地语音识别",
      "fields": [
        {
          "key": "model",
          "label": "服务端当前模型",
          "type": "text",
          "required": true,
          "default": "funasr_sensevoice_small"
        }
      ]
    }
  ]
}
```

字段 type 为 text / secret / boolean / number / select；支持 default、required、readOnly、
min/max/step、options、valueType=number 和 retainWhenOmitted。
消费者按字段契约渲染，不复制 Portal 内部提供商校验和默认值代码。

## 默认与会话

契约通过 `proxyTestPath` 提供代理测试地址。`POST /v1/admin/proxy/test` 接受 `{proxy?: {url?, username?, password?}, target?: "https://example.com/"}`。省略代理设置时使用已保存配置；提供字段时按保存时的验证与凭据保留规则合并，但不写入存储。目标必须为不带凭据或片段的 HTTPS 地址。服务经代理发送 GET，验证证书、不跟随重定向、10 秒超时。响应包含 `ok`、`latencyMs`、收到响应时的 HTTP `status`，以及失败时脱敏的 `error`。HTTP 200–399 视为可用。不发送 ASR 凭据或音频，也不扣除 ASR 配额。

### 上游代理

所有提供商配置都包含布尔字段 `useProxy`（默认 `false`），描述契约也提供此选项。管理设置和管理档案列表包含 `proxy: {url, hasCredentials}`；客户端列表不包含全局代理设置。凭据永不回传。

使用独立的 `PATCH /v1/admin/settings` 请求：`{"proxy":{"url":"https://proxy.example:8443"}}`。地址只接受 HTTP/HTTPS 主机与端口，不允许 URL 内凭据、查询串或路径。可选 `username` 和 `password` 必须同时提供，使用 Portal 密钥保管文件加密保存。同地址省略凭据时保留认证；两个空字符串清除认证。修改或清空地址会清除旧认证，除非同时提供新凭据。空地址移除代理。

勾选的上游（包括 LocalASR）在连接测试和新识别连接中使用代理，同时校验目标及 HTTPS 代理证书。未勾选的档案直接连接，不受环境代理变量影响。代理缺失或不可达会报错，不回退直连。设置变更不改道已建立的连接。代理认证与上游鉴权相互隔离；词典下载不受此设置控制。

首个配置成为默认；可通过 settings 显式修改默认和 `profileOrder`。
客户端不指定 `profileId` 时使用默认，明确指定时使用指定配置。
删除、停用或用尽默认上游后按排序选择下一可用配置，没有则为空。
修改/删除不改写已建立会话的提供商配置快照；配额按后续提交时的实时状态检查。
用量和剩余配额字段、缺失 Token 的处理见下方“用量与额度”。

## 独立网页

### 数据库认证与历史配对兼容（v1）

- `GET /v1/admin/auth/status`：公开返回 initialized/passwordMinLength，未初始化时提供十分钟的 setupChallenge。
- `POST /v1/admin/auth/setup`：`{password,confirmPassword,setupChallenge,pairingCode?}`，一次性事务设置密码；201 返回 token/expiresInMs/localInputApproved。已设置返回 409；不能覆盖已有密码。
- `POST /v1/admin/auth/login`：`{password}`，200 返回 token/expiresInMs；错误密码 401，限流 429，尚未设置 409。
- `POST /v1/admin/auth/logout`：携带管理会话，撤销当前令牌。
- `POST /v1/local-input/pairings`：仅原生回环客户端，`{clientId}`（32 个十六进制字符）；201 返回 id/claimToken/userCode/expiresAt/approvalPath/setupRequired。
- `GET /v1/admin/local-input-pairings?code=...`：需管理会话，返回配对码、到期时间、approved/delivered，不返回私有领取凭据或识别 Key。
- `POST /v1/admin/local-input-pairings`：需管理会话，`{code}` 明确授权 `local-input` Key；也可在首次 setup 时同时确认 pairingCode。
- `POST /v1/local-input/pairings/{id}/claim`：仅原生回环客户端，`{claimToken}`，返回 pending 或 approved/key/keyId/title。
- `POST /v1/local-input/pairings/{id}/ack`：客户端先持久保存 Key 再确认，领取凭据立即失效。

设置/登录接口需要 application/json 和同源浏览器请求，首次挑战绑定调用方和 Host；不信任代理转发头判断本机。
配对有效期十分钟；撤销后不得通过旧配对领回 Key。所有认证响应 no-store。安装与密码恢复见 [使用手册](user-guide.zh-CN.md)。

原生桌面消费者可通过自己的主进程使用同一 HTTP 管理协议：登录取得 `token/expiresInMs`，
在内存中按 Portal origin 保存会话，退出调用 logout，过期重新登录；不保存管理员密码或将短期 token 当作静态 Key。
浏览器请求必须同源，`Origin: null` 及其他页面来源被拒绝；不要在 Electron renderer 直接跨源调用管理 API。
桌面主进程的 IPC 必须限制调用方与允许的管理操作，不提供任意 URL 代理，不取消服务端来源校验。
旧配对接口仅用于已有客户端兼容；新独立客户端由用户配置识别 Key，Windows 联合安装的初始化由产品显式入口完成。

GET /admin 提供浏览器管理页面和同源静态资源。
用户使用管理密码登录；已登录的启动器可 POST /v1/admin/ui-tickets 创建一次性 60 秒票据，
网页用 fragment ticket 交换 /v1/admin/ui-session 的短期管理 token，再立即清除 fragment。
票据只可用一次，短期 token 只授权管理，不授权语音识别接口。
网页资源不包含任何运行时密钥。

## 多个 ASR Key

只有有效短期管理 token 可调用此管理协议，不能用于识别。旧静态管理 Key 不再生效。
POST asr-keys 创建体为 `{"title":"本机输入法"}`，返回 id/title/prefix/createdAt/revoked 和一次性的 `key`。
输入法、Drafts 或其他设备各自保存自己的 ASR Key。Key 可以有多个，识别权限不包含任何管理接口。
GET 列表没有完整 key 或 digest，`canReveal` 表示可否查看。认证仍基于 SHA-256 摘要。
为了支持管理页查看与复制，原值使用 Fernet 认证加密保管；保管密钥在 data/asr-key-vault.key，权限 0600。
`/secret` 仅接受管理会话，普通 ASR Key 无权限；返回设置 no-store。
recover 创建体为 `{"key":"已知原值"}`，必须同时匹配指定 id 的摘要，不能替换别人的 Key 或恢复撤销状态。
旧版未知原值不能从哈希反解，应派生替代 Key。丢失保管文件时返回 KEY_UNAVAILABLE，不静默更换密钥。
备份数据库时必须同时备份 asr-key-vault.key。
DELETE 撤销不可复活，已连接/未连接会话均只清理属于该 Key 的对象，其他 Key 不受影响。
凭据表是向后兼容的 SQLite 增量迁移，不改变已有 profile 与上游密钥。

## 管理界面分类

“公共热词表”提供多表增删改查、文件/联网导入、预览、发布与 JSON 下载。
管理协议路径为 `/v1/admin/hotwords/public-dictionaries`，contract.publicDictionariesPath 提供该入口；
接口字段、独立 revision 及客户端目录关系见下方“公共热词表”。

下游 Key 卡片中的“管理用户热词表”按一个 Key 一个用户查看和管理个人表：新增、调整权重、逐词启用/停用、删除、下载/导入个人 JSON，以及从公共推荐候选区逐词添加。
TXT/TSV/CSV/JSON/RIME 公共推荐文件由管理员在“公共热词表”分类导入并发布；用户保存个人表后才参与识别，
与客户端 Settings 共用相同 owner、存储和 revision；具体路径见下方“管理员代管个人表”。

统一采用侧栏导航、分组表单、卡片和底部状态栏：服务概览、上游 ASR 接入、下游客户端、用量与统计、公共热词表、访问与权限。
上游页面管理提供商 API Key/端点/模型，下游页面管理派生的客户端 ASR Key。
查看、复制、隐藏完整 Key 是独立的用户操作；切换到其他分类或退出管理时清除页面原值。

错误使用 `{error:{code,message,requestId}}`，不以字符串日志替代协议错误。

## 管理员代管个人表

管理员不需要读取 Key 原值；服务按指定 Key 摘要定位相同 owner。下列路径使用管理会话，字段、词语校验、个人 JSON、快照和 revision 语义见 [客户端 API](API.zh-CN.md)。

| 操作                      | 管理路径                                                              |
| ------------------------- | --------------------------------------------------------------------- |
| GET/PATCH 个人设置        | `/v1/admin/asr-keys/{id}/hotwords`                                    |
| DELETE 词频统计           | `/v1/admin/asr-keys/{id}/hotwords/statistics`                         |
| POST 预览/保存快照        | `/v1/admin/asr-keys/{id}/hotwords/dictionaries`                       |
| GET/PATCH/DELETE 单个快照 | `/v1/admin/asr-keys/{id}/hotwords/dictionaries/{dictionary_id}`       |
| GET 推荐目录/正文         | `/v1/admin/hotwords/catalog`、`/v1/admin/hotwords/catalog/{sourceId}` |

客户端与管理员共同编辑同一份个人表；旧 revision 返回 409，不强行覆盖。快照的 enabled 只是兼容字段，不决定识别词。公共表由以下独立管理入口维护。

## 公共热词表

集合路径 `/v1/admin/hotwords/public-dictionaries`：GET 返回 `{dictionaries:[摘要],maxTables:100}`，POST 新建或导入。单表路径 `/{id}`：GET 完整表，PATCH 更新，DELETE 删除。公共表独立 revision，与任何 Key 的个人 revision 无关。

POST 示例：

```json
{
  "title": "医学成像",
  "description": "领域术语",
  "homepage": "https://example.org/terms",
  "license": "自建词表",
  "enabled": true,
  "format": "text",
  "content": "医学成像|4\n神经网络|3\n"
}
```

title 为 1–100 字符，description 最多 2000，license 最多 500，homepage 最多 1000 且为空或 HTTP(S) 网页。enabled 默认 true，必须为布尔值。content 可为空，建立空表；格式和文件限制见客户端 API。每表最多 4 MiB、50000 词，最多 100 表。POST 成功 201，生成 public-... ID，revision 从 1 开始。

`{sourceId:"thuocl-it",preview:true}` 下载固定来源并仅解析，返回 format/words/report/source/recommendationOnly，不写库。content 与 sourceId 互斥，不接受任意 URL 下载。去掉 preview 则导入为新表，未填元信息可取来源描述。

PATCH 示例 `{"revision":1,"title":"新版","format":"text","content":"医学成像|5\n","enabled":false}`。只改元信息时保留正文和来源哈希；改 format 须同时给 content。成功返回完整表并递增 revision。DELETE 接受 `{"revision":2}` → `{ok:true}`；不存在 404 PUBLIC_DICTIONARY_NOT_FOUND，冲突 409 PUBLIC_DICTIONARY_CONFLICT。

摘要含 id/revision/title/description/license/homepage/enabled/format/wordCount/createdAt/updatedAt/source/sha256；完整表增加 words 和 report。words 项为 text/weight/frequency/position，时间为 Unix 秒，sha256 对应最近导入/修改的 UTF-8 正文。报告包含有效、忽略、重复数、警告和前 20 个样例。

AI、计算机、编程入门表只在初始化时写入，保留 tech-ai/tech-computing/tech-programming ID；重启不覆盖管理员修改，也不复活删除项。取消发布或删除表不修改用户已选入的个人词及快照。external 项是下载入口，不会定时覆盖持久公共表。

来源可参考 [THUOCL](https://github.com/thunlp/THUOCL)、[雾凇拼音](https://github.com/iDvel/rime-ice)、[万象拼音](https://github.com/amzxyz/rime-wanxiang)。以实际文件的许可证为准，导入保留来源和条款；RIME 频率不等于 ASR 权重。PDF/扫描图片/文章需在服务外提取正文、OCR 或分词，再人工筛选术语；本 API 没有文档分析能力，也不附带这些工具。

## 用量与额度

PATCH `/v1/admin/asr-keys/{id}/quota` 或 `/v1/admin/profiles/{id}/quota` 接受 `{"remainingSeconds":900,"remainingTokens":null}`；上游可增加 enabled。值是新的余额，不是增量；null 不限额，0 用尽，省略保持原值，不清零累计。时长与 Token 任一耗尽即可阻止后续调用。

管理查询 quota 含 remainingSeconds、remainingTokens、reservedSeconds、availableSeconds、usedSeconds、reportedTokens、tokens、requests、tokenReports、unreportedRequests、enabled、disabledReason、tokenBlocked、exhausted、priority。没有 Token 报告时 tokens 为 null，不是 0。

`GET /v1/admin/usage` 参数：from/to（Unix 秒或 ISO 8601），bucket=hour/day/month，keyId，profileId，timezone（IANA，如 Asia/Shanghai）。默认最近七天、UTC；返回 total/timeline/keys/profiles/trackingStartedAt/resolutionSeconds。普通客户端 `/v1/profiles` 仅见可用状态，不见余额和累计。

时长按提交 PCM 的 32000 字节/秒计量，不按连接等待计时。按完整样本原子扣减，余额边界截取并正常收尾；未连接和过期票据不扣音频，失败/取消保留已用量。上游音频只计一次。Soniox 云端按含空闲的流时长计费，与本地音频配额不同。旧预留列仅保留用于数据库兼容和重启恢复。

`bailian_qwen_asr` 使用 `qwen-audio-3.1-asr-flash-streaming`、官方 WSS `/api-ws/v1/inference`、`language`、`keepDialect` 和服务端 `silenceMs`（200–6000，默认 800），已移除预览间隔。旧 HTTP 设置读取/保存时迁移，保留凭据和配额。`soniox_realtime` 暴露 Key、固定端点/模型（`stt-rt-v6`）、`language`（`auto` 或两位提示代码）及 `endpointDelayMs`（500–3000，默认 2000）。见[百炼](bailian-api-setup.zh-CN.md)和 [Soniox](soniox-api-setup.zh-CN.md)。

管理测试只计上游，未保存草稿用 `draft:提供商:id` 区分。音频历史按分钟压缩，查询向外覆盖完整分钟，余额扣减仍按样本。Portal 不是厂商账单/云余额查询。

Token 采用上游 usage 的 total_tokens 或 input_tokens/output_tokens、prompt_tokens/completion_tokens，不凭文字长度估计。百炼上报任务累计量：只扣增量，重复或过期总量不重复计费，每任务计一次请求/报告。无报告显示未上报，中断任务保留已知部分总量。豆包、LocalASR、Boson 和 Soniox 不提供计费 Token 报告，设置 Token 限额时拒绝选用。百炼最终用量缺失时设置 tokenBlocked，停止后续调用，即使此前已收到部分用量。

Token 在任务完成后结算，最终可能超出余额，真实用量全额入账、余额归零；Token 限额范围内流式任务串行准入，直到正常、错误或取消后的清理。管理员降低余额不能撤销已执行工作。可清除 Token 限额改用时长，或确认上游恢复上报后重新设置预算解除暂停。

上游耗尽或缺少必需报告时自动停用，默认从排序下一项向后循环选可用者，全不可用置空并返回 NO_UPSTREAM_AVAILABLE。自动耗尽者补预算可恢复；手动停用须显式启用；管理员明确清空默认不会被补预算覆盖。`profileOrder` 必须完整包含所有档案且不重复，可和 defaultProfileId 原子更新。切换只影响新会话，不拼接活动录音。

用量与余额事务保存。重启释放遗留预留并标记 interrupted；无法取得 Token 报告的限额账户暂停。删除档案或撤销 Key 保留历史，不补算启用计量前的用量。

## 安装初始化与迁移

首次密码至少 12 字符，scrypt 加盐哈希；管理会话默认 30 分钟，退出即撤销。默认回环监听；在本机初始化后再开放远程地址。安装不重置已有密码。

Windows 联合 MSI 在用户正常授权并选择 Portal 后，通过 Portal 所有者入口为安装用户 SID 分配/复用 local-input Key，再通过 ACL 保护的文件交给 Input 自己的配置入口。Key 不放 MSI 属性或命令行；同一交接代次不覆盖后来选定的连接，撤销的 Key 不复活。独立安装和远程连接仍由用户配置。

迁移保留业务数据。旧 OPENASRPORTAL_ADMIN_KEY/API_KEY 不再导入；deb 移除 service.env 的旧凭据行，Windows 清除 service.json 的旧 apiKey/adminKey，保留其他运行参数。Docker 不生成旧凭据 JSON；仅存在于旧环境变量的识别 Key 要重新派生。恢复密码必须指定实际已有数据库目录，撤销管理会话但保留识别 Key 与业务数据。
