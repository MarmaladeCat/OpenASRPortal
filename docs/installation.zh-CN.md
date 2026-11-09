# 持久化安装与语言选择

[English](installation.md) | **简体中文**

本页行为适用于 Portal 1.1.0 及 Input 1.1.0 + Portal 1.1.0 合体安装包。

## 配合 Input 安装

[OpenASRInput](https://github.com/MarmaladeCat/OpenASRInput) 采集音频并向应用输入文字，Portal 负责连接识别提供商。[Input Release 页](https://github.com/MarmaladeCat/OpenASRInput/releases) 是 Windows x64 MSI、Linux amd64/ARM64 单个合体 DEB 的计划分发入口。APT 用 `openasrinput-portal` 管理两个应用，替换独立包并保留数据，详见 [合体安装手册](https://github.com/MarmaladeCat/OpenASRInput/blob/main/docs/installation.zh-CN.md)。独立 Portal 包仍从 [Portal Release](https://github.com/MarmaladeCat/OpenASRPortal/releases) 获取。

每个包都有同名 `文件名.sha256`，只含该包的校验记录。合体安装通过产品公开配置命令，为本机 Input 配置独立 ASR Key；管理员密码和上游提供商 Key 与之分开。

## 目录与生命周期

Windows 服务配置在 `%ProgramData%\OpenASR\Portal\service.json`，默认数据在其 `data\` 子目录；Linux 使用 `/var/lib/openasr/portal/service.env` 和 `/var/lib/openasr/portal/data/`。Input 位于同根下的 `Input/<SID>` 或 `input/<uid>`，具有用户私有权限。只有 Portal 打开自身数据库。

升级时，旧默认 `%ProgramData%\OpenASRPortal`、`/etc/openasrportal/service.env`、`/var/lib/openasrportal` 在停止 Portal 后迁移。已配置的自定义数据目录保留。确认新安装正常前保留旧备份。Docker 卷和源码运行的 `--data-dir` 仍由部署者明确指定。

Linux 安装会在 `/etc/systemd/system/openasrportal.service.d/20-data-directory.conf` 中，仅为配置的数据目录添加 systemd 沙箱例外。之后修改 `OPENASRPORTAL_DATA` 时，请停止服务并运行 `sudo dpkg-reconfigure openasrportal` 更新该例外。已有自定义数据文件应继续允许 `openasrportal` 服务账号访问。

合体 DEB 改用 `sudo dpkg-reconfigure openasrinput-portal`。包安装不打开浏览器；图形/root 安装后，从应用菜单打开 **OpenASR Input + Portal 配置**，或运行 `sudo openasrinput-portal-setup --user 账户 --no-open` 连接该账户。sudo 安装会自动连接调用账户。

Windows 首次交互安装或 Linux 配置入口在实时认证状态表明尚无管理员时打开 `/admin/setup`。设置至少 12 字符的密码后添加上游。升级及保留配置后的重装复用管理员、客户端 Key、识别档案、热词和配额；没有完成的首次设置会继续引导。Windows 可用 `OPENASRPORTAL_NO_LAUNCH=1` 或 `/qn` 禁止自动打开，Linux 配置入口使用 `--no-open`。无图形界面时手动访问本机实际管理地址；独立 Linux 包会打印该地址，并在能识别 sudo 发起用户的图形会话时尝试打开初始化页面。

默认卸载保留配置。Windows 明确删除数据时也会清理识别出的旧默认备份；Linux 删除数据是独立的管理员操作。删除前备份实际数据目录，至少包含 `portal.db` 和 `asr-key-vault.key`。

## 界面语言

设置、登录及所有管理分区右上角均有 **中文 / English**。默认跟随浏览器/系统，浏览器单独记忆 Portal 的语言选择，与 Input 相互独立。切换不会提交或重置表单；用户名称、词表内容、提供商 ID、地址和凭据保持原值。
