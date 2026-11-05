# OpenASRPortal 独立容器部署

[English](README.md) | **简体中文**

本包提供 Portal 镜像与两种独立 Compose 方案。先核对 image.json 的系统/CPU 与 Docker 主机一致；Windows/macOS Docker Desktop 使用匹配架构的 Linux 容器。镜像不含客户端、LocalASR 或模型。

以下命令使用 Compose 插件；若安装的是独立 Compose v2 可执行文件，将 `docker compose` 替换为 `docker-compose`。

## 本机 HTTP

在解压后的本目录执行：

```bash
docker load -i image.tar
cp .env.example .env
# Linux：数据目录须允许容器内 UID 10001 写入。
mkdir -p data
sudo chown 10001:10001 data
docker compose up -d
docker compose logs portal
```

默认访问 `http://127.0.0.1:10087/admin`，设置至少 12 字符的管理密码，再配置上游、派生客户端 Key。密码和 Key 由数据库管理，不生成凭据 JSON。客户端手工填写 Portal 地址和自己的识别 Key。

`.env` 中 IMAGE 选择导入的镜像，BIND/PORT 控制宿主监听，DATA 默认为 `./data`。改 DATA 时，相应目录也要具有写权限。Docker Desktop 的共享目录权限由宿主配置，需确认服务能写入。`docker compose down` 停止 HTTP 方案并保留绑定目录。

## 单实例 HTTPS

`compose.https.yaml` 是**单独使用的完整方案**：NGINX 发布 80/443，Portal 只在容器网络监听，数据保存在 `portal-data` 命名卷。用 `docker compose -f compose.https.yaml ...` 启停；它不读取 HTTP 方案的 DATA/BIND/PORT，HTTPS 绑定地址由 `OPENASRPORTAL_HTTPS_BIND` 控制，默认回环。端口和 `./tls` 证书目录直接写在 Compose 中，`.env.example` 没有域名或 TLS 路径变量。

两个文件不是基础层与覆盖层，不要直接叠加：合并会混入两套端口/卷定义，部分 Compose 版本还会因重复 extra_hosts 拒绝校验。已有 HTTP 数据的迁移见下文。

1. 按上文导入 Portal 镜像、复制 `.env`。额外准备 `nginx:1.28-alpine`（联网执行 `docker pull nginx:1.28-alpine`；离线时提前导入同架构镜像）。本包的 image.tar 只含 Portal。
2. 准备覆盖实际 DNS 名/IP 的证书，放为 `tls/server.crt` 与 `tls/server.key`。已有可信证书时使用完整证书链；自签名演示可使用下面命令。

```bash
# Linux；在临时容器中使用镜像已有的 Python/cryptography，宿主无需安装 Python。
docker compose -f compose.https.yaml run --rm --no-deps --user "$(id -u):$(id -g)" -v "$PWD:/work" --entrypoint python portal /work/create_tls_certificate.py --host localhost --host 127.0.0.1 --output /work/tls
docker compose -f compose.https.yaml up -d
docker compose -f compose.https.yaml ps
curl --cacert tls/server.crt https://localhost/health
```

生成时用重复的 `--host` 加入客户端实际访问的主机名/IP，不含协议或端口。默认有效期 365 天，可用 `--days` 指定 1–3650 天。脚本拒绝覆盖已有证书。Windows PowerShell 可将证书生成命令中的 `--user "$(id -u):$(id -g)"` 改为 `--user 0:0`，卷参数写作 `-v "${PWD}:/work"`。

3. 先在本机访问 `https://localhost/admin` 初始化。自签名证书应先核对指纹，再把 **server.crt** 导入每个客户端实际使用的信任库；浏览器、Python 和 Node 可能使用不同证书库，分别确认。仅复制公有证书，server.key 留在服务器。不要关闭 TLS 校验。
4. 远程访问时，在 `.env` 增加 `OPENASRPORTAL_HTTPS_BIND=0.0.0.0` 或具体网卡地址，再执行同一 `-f` 的 `up -d`。使用证书包含的名称连接；客户端直接填 HTTPS，不能依赖 HTTP 重定向（客户端可能拒绝重定向）。NGINX 支持 WS 升级与流式转发。

## 数据迁移、备份与维护

HTTP 使用宿主目录；HTTPS 使用 Compose 项目名下的 `portal-data` 卷，二者不会自动共享数据。保留数据目录/卷中的全部文件，尤其 `portal.db` 和 `asr-key-vault.key`。先停止对应服务再备份，避免漏掉 SQLite WAL。

从已有 HTTP 方案切换且希望沿用原目录：先 `docker compose down`，备份 data/，将 `compose.https.yaml` 中 Portal 的卷改为 `./data:/data`（或你的实际路径），确认 UID 10001 写权限，再仅使用 HTTPS 文件启动。核验登录、档案、热词和 Key。若不迁移，新的命名卷会表现为首次初始化，不是旧数据丢失。

命名卷随 Compose 项目名关联；移动部署目录时固定相同项目名（`-p <原项目名>`）或显式迁移卷。`docker compose -f compose.https.yaml down` 保留命名卷，`down -v` 会删除它。升级时导入新镜像、更新 `.env` 中 IMAGE，然后对原方案执行 up -d。

轮换证书时先在新目录生成并验证，保留旧证书回退副本，将新证书/私钥成对替换到 tls/，再执行 `docker compose -f compose.https.yaml exec nginx nginx -t` 和 `docker compose -f compose.https.yaml exec nginx nginx -s reload`。自签名换证后客户端也需更新信任。

故障检查：`docker compose -f compose.https.yaml logs --tail 100 portal nginx`。NGINX 等待 Portal healthy；502 检查服务健康和容器网络，证书错误检查 SAN/有效期/客户端信任。Portal 连接宿主 LocalASR 可使用 Compose 已配置的 `host.docker.internal`，但宿主服务仍需监听容器可达的接口；另一 Compose 项目的服务名需共享网络才能解析。
