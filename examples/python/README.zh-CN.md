# 可复制的 Python ASR 客户端

[English](README.md) | **简体中文**

使用 Python 3.10+ 和 Portal 派生的客户端 ASR Key。将此目录复制到自己的程序即可；不导入 Portal 或其他产品源码，只依赖 `aiohttp`。

```bash
python -m venv .venv
# Windows 改用 .venv\Scripts\python.exe
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python transcribe.py recording.wav --portal http://127.0.0.1:10087
```

命令以不回显方式询问 ASR Key，也支持环境变量 `OPENASR_ASR_KEY`。不要把 Key 写入命令行参数或源码。WAV 必须为未压缩 PCM16、16 kHz、单声道；文件辅助函数剥离 WAV 头，按实时速度上传所有样本，包括静音。`--profile ID` 选择 Portal 档案，省略时使用默认档案。HTTPS 自动对应 WSS。

## 嵌入程序

```python
import asyncio
from openasr_client import PortalClient, wav_chunks

async def recognize(origin, asr_key, wav_path):
    async with PortalClient(origin, asr_key) as client:
        return await client.transcribe(wav_chunks(wav_path))

# 将 wav_chunks(...) 换成麦克风的异步 bytes 迭代器即可。
# 同步程序可用 asyncio.run(recognize(...)) 启动。
```

`on_event=callback` 同步接收已校验事件，回调应快速返回。partial 应替换对应语句的预览，不能逐次追加修订。最终文本按语句顺序直接拼接，不人为添加空格，保留上游原始拼写与标点。`transcribe()` 只有在 `session.finished` 合法、finalCount 一致且没有未定稿的非空预览时返回。需要即时上屏时，在自己的事件循环中对每个唯一 final 提交一次；取消不能撤回已提交内容。

使用 `task.cancel()` 并等待该任务来取消；清理本任务会话后继续抛出 `CancelledError`。不会自动重试或重放音频。HTTP/WS 重定向被拒绝，票据仅用于原始同源会话路径，传输异常收敛为安全错误码，无终态断连算失败。创建重试 ID 可选，只用于同一创建请求的重试，不能用于重放录音。

这是小型参考客户端，不提供麦克风驱动或重采样。每次调用为一轮 v1，会话使用五分钟与协商录音上限的较小值；消费 `effectiveSessionLimits`、描述符的 `readyTimeoutMs`（旧服务回退 45 秒）及 Portal 收尾预算。响应有界，超长录音不会偷偷拆成多次请求。能力协商、额度、热词和错误见[完整 API](../../docs/API.zh-CN.md)及[快速接入指南](../../docs/python-client.zh-CN.md)。
