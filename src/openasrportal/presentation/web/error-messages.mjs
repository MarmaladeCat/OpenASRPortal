export const errorMessages = {
  '请求体必须是 JSON 对象': 'Request body must be a JSON object',
  'Portal 接入凭据无效': 'Invalid Portal credentials',
  '请通过本机 Portal 地址访问管理页面': 'Open administration using the local Portal address',
  此接口仅允许本机输入法发起配对: 'Only local input clients can start pairing here',
  '管理密码已经设置，请登录': 'Administrator password already set. Log in.',
  '请使用 JSON 请求': 'Use a JSON request',
  '首次设置页面已失效，请刷新后重试': 'Setup page expired. Refresh and retry.',
  两次输入的密码不一致: 'The passwords do not match',
  输入法配对码无效: 'Invalid input client pairing code',
  'ASR Key 创建体必须是对象': 'ASR key creation body must be an object',
  'ASR Key 不存在': 'ASR key not found',
  识别配置不存在: 'Recognition profile not found',
  '请提供原始 ASR Key': 'Provide the original ASR key',
  '不能恢复已撤销的 Key': 'Revoked keys cannot be restored',
  '原值与此 Key 不匹配': 'Original value does not match this key',
  '公开词库来源 ID 无效': 'Invalid public dictionary source ID',
  公共热词表不存在或未发布: 'Public dictionary missing or unpublished',
  未知的公共热词表字段: 'Unknown public dictionary field',
  公共热词表不存在: 'Public dictionary not found',
  未知的词库导入字段: 'Unknown dictionary import field',
  'preview 必须为布尔值': 'preview must be a boolean',
  '请填写合法且唯一的配置 id': 'Enter a valid, unique profile ID',
  '配置 id 已存在': 'Profile ID already exists',
  配置名称无效: 'Invalid profile name',
  未知的默认配置或排序字段: 'Unknown default profile or ordering field',
  '管理页面凭据已失效，请重新登录': 'Administrator session expired. Log in again.',
  '识别配置 id 无效': 'Invalid recognition profile ID',
  配置必须为对象: 'Configuration must be an object',
  配置不存在: 'Profile not found',
  配置标题无效: 'Invalid profile title',
  会话请求必须为对象: 'Session request must be an object',
  'clientRequestId 无效': 'Invalid clientRequestId',
  'Portal 会话容量已满': 'Portal session capacity reached',
  '当前支持 PCM16 / 16kHz / 单声道': 'PCM16 / 16 kHz / mono is supported',
  '识别配置 ID 无效': 'Invalid recognition profile ID',
  一次性连接凭据无效: 'Invalid single-use connection ticket',
  连接凭据已过期: 'Connection ticket expired',
  '需要 WebSocket 连接': 'A WebSocket connection is required',
  管理请求来源无效: 'Invalid management request origin',
  '初始化请求过多，请稍后重试': 'Too many setup requests. Try again later.',
  '此 Key 已撤销': 'This key has been revoked',
  未知的热词更新字段: 'Unknown hotword update field',
  '公开词库下载失败，可下载原文件后上传':
    'Dictionary download failed. Download the original file and upload it.',
  请选择词表内容或联网来源之一: 'Choose dictionary contents or an online source, not both',
  未知的词表格式: 'Unknown dictionary format',
  '词库不存在或不属于此 Key': 'Dictionary not found or owned by another key',
  未知的词库修改字段: 'Unknown dictionary update field',
  请选择上传内容或公开来源之一: 'Choose uploaded contents or a public source, not both',
  测试配置必须为对象: 'Test configuration must be an object',
  'Portal 尚未设置默认识别配置': 'Portal has no default recognition profile',
  会话不属于当前调用方: 'Session belongs to another caller',
  客户端连接已关闭: 'Client connection closed',
  会话超过五分钟上限: 'Session exceeded the five-minute limit',
  '请求 JSON 无效': 'Invalid request JSON',
  请求参数无效: 'Invalid request parameters',
  '预览或格式变更须提供 content 或 sourceId':
    'Preview or format changes require content or sourceId',
  该请求已建立识别连接: 'This request already has a recognition connection',
  '所有上游 ASR 已停用或额度耗尽，请管理员补充额度':
    'All upstreams are disabled or exhausted. Ask an administrator to adjust quotas.',
  '上游提前结束，尚未完成音频提交': 'Upstream ended before audio submission completed',
  等待最终定稿超时: 'Timed out waiting for final text',
  '统计时间请使用 Unix 秒数或 ISO 8601 格式': 'Use Unix seconds or ISO 8601 timestamps',
  'PCM16 字节数必须为偶数': 'PCM16 data must contain an even number of bytes',
  录音超过五分钟上限: 'Recording exceeded the five-minute limit',
  未知的控制消息: 'Unknown control message',
  控制消息必须为对象: 'Control message must be an object',
  '上游识别失败，请检查 Portal 配置与网络':
    'Upstream recognition failed. Check Portal configuration and network.',
  未知的公开词库来源: 'Unknown public dictionary source',
  '公开词库超过 4 MiB，请下载并拆分后上传':
    'Public dictionary exceeds 4 MiB. Download, split, and upload it.',
  '{0} 语音连接异常，请检查后端网络并重试':
    '{0} speech connection failed. Check the backend network and retry.',
  '{0} 连接或识别响应超时，请检查网络后重试':
    '{0} connection or recognition timed out. Check the network and retry.',
  '未知的远程 ASR 提供商': 'Unknown remote ASR provider',
  '远程 ASR 配置必须为对象': 'Remote ASR configuration must be an object',
  '请填写有效的 ASR API Key': 'Enter a valid ASR API key',
  '请使用豆包官方实时识别 WebSocket 端点': 'Use the official Doubao real-time WebSocket endpoint',
  '不支持的豆包模型资源 ID': 'Unsupported Doubao model resource ID',
  二遍识别选项必须为布尔值: 'Second-pass recognition must be a boolean',
  '请填写 OpenLocalASR 的 ws(s)://主机:端口/api-ws/v1/inference 地址':
    'Enter the OpenLocalASR ws(s)://host:port/api-ws/v1/inference address',
  请填写远程服务当前启用的模型名称: 'Enter the model currently enabled by the remote service',
  '百炼端点必须为官方 HTTPS 地址': 'Bailian endpoint must be an official HTTPS address',
  '请使用百炼北京/新加坡官方 HTTPS 根地址、/api/v1 或完整 multimodal-generation/generation 地址；此适配器不使用 OpenAI 兼容协议':
    'Use the official Bailian Beijing/Singapore HTTPS origin, /api/v1, or full multimodal-generation/generation path. This adapter does not use OpenAI-compatible APIs.',
  不支持的百炼识别语种: 'Unsupported Bailian recognition language',
  保留方言选项必须为布尔值: 'Preserve dialect must be a boolean',
  '预览间隔必须为 0 / 1500 / 2500 / 4000 毫秒':
    'Preview interval must be 0 / 1500 / 2500 / 4000 ms',
  '断句静音应为 600–3000 毫秒': 'Segmentation silence must be 600–3000 ms',
  '此适配器使用 {0}': 'This adapter uses {0}',
  词频无效: 'Invalid word frequency',
  词频须为非负有限数值: 'Word frequency must be a nonnegative finite number',
  'RIME 词库缺少 YAML 结束标记 ...': 'RIME dictionary is missing the YAML end marker ...',
  'RIME columns 必须包含唯一的 text 列': 'RIME columns must contain exactly one text column',
  '请提供 UTF-8 文本词库': 'Provide a UTF-8 text dictionary',
  '单个词库文件最多 4 MiB，请拆分大词库':
    'Dictionary files must not exceed 4 MiB. Split larger files.',
  不支持此词库格式或二进制文件: 'Unsupported dictionary format or binary file',
  词库没有正文: 'Dictionary has no contents',
  '没有有效热词；RIME 入口文件须导入其 import_tables 引用的正文词库':
    'No valid hotwords. Import the dictionaries referenced by the RIME entry file’s import_tables.',
  '一个词库最多 50000 个有效词，请拆分后导入':
    'A dictionary allows up to 50,000 valid words. Split it before importing.',
  'import_tables 引用不自动展开；请另行导入：{0}':
    'import_tables references are not expanded automatically. Import separately: {0}',
  词条须为对象: 'Dictionary entries must be objects',
  'ASR 权重须为 1–5': 'ASR weights must be 1–5',
  'RIME columns 请使用列表格式': 'RIME columns must use a list',
  'JSON 词库须为词语数组或词语/权重对象':
    'JSON dictionaries must be word arrays or word/weight objects',
  当前本地模型接口不支持会话级热词增强:
    'The current local model does not support per-session hotwords',
  热词必须是文本: 'Hotword must be text',
  "热词须为 2–64 字符的词语，可使用文字、数字、空格及常见技术符号 .+#-/_'":
    "Hotwords must be 2–64 characters: letters, numbers, spaces, or .+#-/_'",
  未知的热词设置字段: 'Unknown hotword setting',
  '双向流式热词上限 100 tokens；Portal 保守按 UTF-8 字节预算选词，非 100 个词':
    'Streaming hotwords have a 100-token limit. Portal selects conservatively by UTF-8 bytes, not 100 words.',
  'Qwen Audio 3.1 即时热词最多 2000 个；普通权重 1–5':
    'Qwen Audio 3.1 supports up to 2,000 instant hotwords with weights 1–5',
  '手动热词最多 {0} 个': 'Up to {0} manual hotwords are allowed',
  '手动热词使用 text / weight 字段': 'Manual hotwords use text / weight fields',
  '热词权重须为 1–5 的整数': 'Hotword weight must be an integer from 1 to 5',
  热词不可重复: 'Duplicate hotwords are not allowed',
  '排除热词最多 {0} 个': 'Up to {0} excluded hotwords are allowed',
  '{0} 必须为布尔值': '{0} must be a boolean',
  '{0} 必须为 {1} 的整数': '{0} must be an integer in {1}',
  '百炼响应缺少识别文本，不能作为正常定稿':
    'Bailian response contains no recognized text and cannot be treated as a final result',
  百炼返回了无效的识别结果: 'Bailian returned an invalid recognition result',
  '百炼识别请求失败，请检查模型权限、账户额度与音频格式':
    'Bailian recognition failed. Check model access, account quota, and audio format.',
  百炼录音会话已经结束: 'Bailian recording session ended',
  '百炼识别请求超时，请检查网络后重试':
    'Bailian recognition timed out. Check the network and retry.',
  '无法连接百炼，请检查后端网络及端点地址':
    'Cannot connect to Bailian. Check backend network and endpoint.',
  '百炼返回了无效 JSON 响应': 'Bailian returned invalid JSON',
  '百炼调用失败（HTTP {0}），请检查 API Key、地域、模型权限和额度':
    'Bailian request failed (HTTP {0}). Check API key, region, model access, and quota.',
  '百炼识别请求积压，请停止录音并检查网络后重试':
    'Bailian requests are backlogged. Stop recording, check the network, and retry.',
  'OpenLocalASR 未确认任务启动': 'OpenLocalASR did not confirm task startup',
  'OpenLocalASR 结果缺少文本': 'OpenLocalASR result contains no text',
  'OpenLocalASR 任务失败，请检查服务模型是否就绪、模型名和音频参数':
    'OpenLocalASR task failed. Check model readiness, model name, and audio settings.',
  'OpenLocalASR 返回了无效的 DashScope 任务事件':
    'OpenLocalASR returned an invalid DashScope task event',
  'OpenLocalASR 未返回最终分句，文字已保留供核对':
    'OpenLocalASR did not return a final utterance. Text retained for review.',
  'OpenLocalASR 连接失败（HTTP {0}），请检查地址和 API Key':
    'OpenLocalASR connection failed (HTTP {0}). Check address and API key.',
  豆包返回了无效的数据帧: 'Doubao returned an invalid data frame',
  豆包返回了不支持的协议帧: 'Doubao returned an unsupported protocol frame',
  豆包响应数据解析失败: 'Cannot parse Doubao response',
  '豆包识别失败（代码 {0}），请检查 Key、服务开通状态、额度和音频格式':
    'Doubao recognition failed (code {0}). Check key, service activation, quota, and audio format.',
  '豆包鉴权/连接失败（HTTP {0}），请检查 API Key、模型资源及服务额度':
    'Doubao authentication/connection failed (HTTP {0}). Check API key, model resource, and quota.',
  请先发送语音开始信号: 'Send the speech-start signal first',
  '{0} 未及时返回最终结果，请重新开始录音':
    '{0} did not return a final result in time. Start recording again.',
  '音频必须为 16 kHz 单声道 PCM16': 'Audio must be 16 kHz mono PCM16',
  '管理密码须为 12–1024 个字符': 'Administrator password must be 12–1024 characters',
  '尝试过于频繁，请稍后重试': 'Too many attempts. Try again later.',
  '管理密码不能使用已有的识别 Key': 'Administrator password cannot be an existing recognition key',
  请先设置管理密码: 'Set the administrator password first',
  管理密码错误: 'Incorrect administrator password',
  输入法客户端标识无效: 'Invalid input client identity',
  '输入法配对不存在或已过期，请在输入法中重新发起':
    'Input pairing missing or expired. Start again from Input.',
  '输入法配对不存在或已过期，请重新发起': 'Input pairing missing or expired. Start again.',
  输入法配对凭据无效: 'Invalid input pairing credentials',
  '输入法配对已过期，请重新发起': 'Input pairing expired. Start again.',
  '本机输入法 Key 已撤销，请重新配对并授权': 'Local input key revoked. Pair and authorize again.',
  '管理密码已更新，请重新登录': 'Administrator password changed. Log in again.',
  '配对请求过多，请稍后重试': 'Too many pairing requests. Try again later.',
  '热词设置或词库已更新，请刷新后重试': 'Hotwords or dictionaries changed. Refresh and retry.',
  '词库名称须为 1–100 字符': 'Dictionary name must be 1–100 characters',
  '热词设置已更新，请刷新后重试': 'Hotword settings changed. Refresh and retry.',
  '每个 Key 最多 8 个词库，请先删除不需要的词库':
    'Each key supports up to 8 dictionaries. Remove unused ones first.',
  '词库更新仅接受 title / enabled': 'Dictionary updates accept only title / enabled',
  'ASR Key 密钥保管文件不可用，请从备份恢复 asr-key-vault.key':
    'ASR key vault unavailable. Restore asr-key-vault.key from backup.',
  '无法解密此 ASR Key，请检查密钥保管文件是否与数据库匹配':
    'Cannot decrypt this ASR key. Check that the vault key matches the database.',
  请填写公共热词表名称: 'Enter a public dictionary name',
  '来源网页须为 HTTP/HTTPS 地址': 'Source website must be an HTTP/HTTPS address',
  '{0} 必须为不超过 {1} 字符的文本': '{0} must be text of at most {1} characters',
  '公共热词表最多 100 张，请先删除不需要的表':
    'Up to 100 public dictionaries are supported. Remove unused ones first.',
  '公共热词表已更新，请刷新后重试': 'Public dictionary changed. Refresh and retry.',
  '切换到不提供 Token 用量的上游前，请先清除该配置的 Token 限额':
    'Clear the token limit before switching to an upstream without token reports',
  '默认 ASR 配置不存在': 'Default ASR profile not found',
  '请填写 1–100 字符的 ASR Key 名称': 'Enter an ASR key name of 1–100 characters',
  '此 Key 已撤销，不能查看或复制': 'This key is revoked and cannot be viewed or copied',
  '此旧 Key 仅有哈希，无法反解；需要导入原值或派生替代 Key':
    'This legacy key has only a hash. Import the original or issue a replacement.',
  '已有加密 ASR Key，但保管文件缺失；请恢复备份，不自动更换保管密钥':
    'Encrypted ASR keys exist but the vault key is missing. Restore a backup; it will not be replaced automatically.',
  '剩余时长必须为可保存的非负秒数，或 null（不限额）':
    'Remaining time must be storable nonnegative seconds or null (unlimited)',
  '剩余时长必须为非负秒数，或 null（不限额）':
    'Remaining time must be nonnegative seconds or null (unlimited)',
  剩余时长超出可保存范围: 'Remaining time exceeds the supported range',
  '剩余 Token 必须为非负整数，或 null（不限额）':
    'Remaining tokens must be a nonnegative integer or null (unlimited)',
  计量账户不存在: 'Metering account not found',
  '上游未返回可计量的 Token；请管理员改用时长限额或调整配额':
    'Upstream did not report metered tokens. Ask an administrator to use time limits or adjust quotas.',
  '指定上游 ASR 已停用，请选择其他配置或跟随默认':
    'Selected upstream disabled. Choose another profile or follow the default.',
  '上游顺序必须为配置 ID 数组': 'Upstream order must be an array of profile IDs',
  '上游顺序必须包含全部现有配置，且不能重复':
    'Upstream order must contain every profile exactly once',
  '未知的配额字段，请填写剩余秒数、剩余 Token 或上游启用状态':
    'Unknown quota field. Use remaining seconds, remaining tokens, or upstream enabled state.',
  上游启用状态必须为布尔值: 'Upstream enabled state must be a boolean',
  '此上游不提供 Token 用量，请使用时长限额':
    'This upstream does not report tokens. Use a time limit.',
  计量会话已经结束: 'Metering session ended',
  '计量音频必须包含完整 PCM16 样本': 'Metered audio must contain complete PCM16 samples',
  '上游没有返回 Token 用量，已停止 Token 限额会话；请改用时长限额':
    'Upstream did not report tokens. Token-limited session stopped; use a time limit.',
  '统计分组应为 hour / day / month': 'Statistics buckets must be hour / day / month',
  统计开始时间必须早于结束时间: 'Statistics start must precede end time',
  '{0}的剩余额度已用尽，请管理员补充额度': [
    '{0} quota exhausted. Ask an administrator to replenish it.',
    [0]
  ],
  '此上游不提供 Token 用量；请改用时长限额或选择支持 Token 的上游':
    'This upstream does not report tokens. Use time limits or select a metered upstream.',
  统计时区无效: 'Invalid statistics timezone',
  '客户端 Key 的 Token 额度不可继续使用': 'Client key token budget cannot be used further',
  '上游剩余时长不足以完成当前片段，请管理员调整额度':
    'Upstream time budget is insufficient for this segment. Ask an administrator to adjust it.'
};
