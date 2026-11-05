# OpenASRPortal 功能测试

[English](README.md) | **简体中文**

[manifest.json](manifest.json) 定义场景、预期与命令；[requirements.txt](requirements.txt)
固定协议和管理服务依赖。测试不使用正式上游 Key。

- `service-lifecycle`：实际服务子进程首次设置、创建识别 Key/profile、重启保持配置、正常退出及端口冲突。
- `admin-login`：实际浏览器和独立 Portal 进程的首次密码设置、确认、登录、清空密码框、退出。
- `profile-management`：实际管理页面的 profile、Key、配额操作与密钥隔离；识别上游为模拟服务。

在本产品仓库根目录执行，Python 3.10+：

```bash
python scripts/test.py setup --suite core
python scripts/test.py run --suite core
python scripts/test.py setup --suite ui
python scripts/test.py run --suite ui
```

入口准备独立测试 venv，Python 搜索路径为 `src` 和 `tests`。UI 使用 Electron 44.4.5，执行器设置 `OPENASRPORTAL_TEST_PYTHON`，Linux 自动经 Xvfb 启动；主机须具备 Xvfb 和浏览器所需系统库。

测试数据库/凭据全部在 `test-results/` 的临时目录，进程使用独立端口并自行回收；
环境/下载在 `.cache/`，不进 Git。ARM64 执行服务 `core`，Windows 执行 `core/ui`。
真实云端识别及 MSI 的系统服务安装/升级/卸载需另行验收，见 [测试约束](../../docs/testing.zh-CN.md)；构建准备见 [开发说明](../../docs/development.zh-CN.md)。
