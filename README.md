# semantic-sandbox

一个用来**动手学习向量数据库**的练习项目：同一份数据，分别用 **Milvus / Weaviate / Qdrant** 三套主流向量库各自实现一次"入库 + 语义检索"的完整流程。

目标读者：**有约一年 Python 经验、第一次接触向量数据库**的开发者。

---

## 目录

- [架构概览](#架构概览)
- [快速上手](#快速上手)
- [Web UI](#web-ui)
  - [Makefile 快捷命令](#makefile-快捷命令)
  - [示例数据一键加载](#示例数据一键加载)
  - [健康检查端点](#健康检查端点)
- [API 接口说明](#api-接口说明)
- [带元数据过滤的检索](#带元数据过滤的检索)
- [性能基准测试](#性能基准测试)
- [示例数据集](#示例数据集)
- [嵌入模型](#嵌入模型)
- [Docker 安装与配置](#docker-安装与配置)
- [服务器部署](#服务器部署)
- [三者对比速查](#三者对比速查)
- [目录结构](#目录结构)
- [目录读图建议](#目录读图建议)
- [常见问题](#常见问题)
- [License](#license)

---

## 架构概览

```
  ┌─────────────┐      ┌──────────────────┐      ┌─────────────────┐
  │  原始文本    │ ───► │ 嵌入模型          │ ───► │ 向量 (float[])  │
  │ "埃菲尔铁塔" │      │ sentence-         │      │ [0.12, -0.03,   │
  │              │      │ transformers      │      │  ..., 0.41]     │
  └─────────────┘      └──────────────────┘      └────────┬────────┘
                                                            │
                                                            ▼
  ┌────────────────────────────────────────────────────────────────┐
  │               向量数据库 (Milvus / Weaviate / Qdrant)           │
  │       存储向量 + 建立索引 + 支持"给一个向量找最相近的 N 条"      │
  └─────────────────────────────┬──────────────────────────────────┘
                                 │
                                 ▼
     查询 "巴黎地标" ─► 嵌入 ─► 拿查询向量去库里做近邻检索 ─► Top-K 结果
```

本项目包含**两个独立组件**，两个都要启动：

```
  ┌─────────────────────────────┐        ┌─────────────────────────────┐
  │ 组件 A：向量数据库            │        │ 组件 B：嵌入模型              │
  │ (跑在 Docker 容器里)          │        │ (跑在你本机 Python 里)        │
  │                             │        │                             │
  │ Qdrant / Weaviate / Milvus   │        │ sentence-transformers +      │
  │ 存向量、建索引、做检索         │        │ 模型权重文件                  │
  │ 通过 docker compose 启动      │        │ 通过 pip install + 预下载     │
  └─────────────────────────────┘        └─────────────────────────────┘
```

---

## 快速上手

### 前置要求

| 工具 | 版本 | 说明 |
|---|---|---|
| Python | 3.10+ | 建议用 `venv` 创建虚拟环境 |
| Docker | 20+ | 用来启动向量库服务；**Milvus 要求至少 4GB 内存** |
| Docker Compose | v2 | 命令为 `docker compose`（空格），不是老版 `docker-compose` |

```bash
python3 --version && docker --version && docker compose version
```

### 三步部署

```bash
# 步骤 1：准备嵌入模型（只需做一次）
cd semantic-sandbox
python3 -m venv .venv && source .venv/bin/activate

# 国内网络先执行（跳过 HuggingFace 官网直连）
# export HF_ENDPOINT=https://hf-mirror.com

pip install sentence-transformers python-dotenv   # 约 1-2GB，需几分钟
python scripts/preload_model.py                   # 下载模型到 ./models/（约 185MB）

# 步骤 2：启动向量数据库（推荐先从 Qdrant 开始）
cd qdrant-demo
cp .env.example .env
docker compose up -d                              # 启动数据库容器
pip install -r requirements.txt                   # 装 Python 客户端

# 步骤 3：入库 + 搜索
python -m src.ingest                              # 文本 → 向量 → 写入数据库
python -m src.search                              # 交互式语义搜索
```

> **推荐从 Qdrant 开始**：单容器、启动约 3 秒、内存 ≥1GB 即可。跑通后再对比 Weaviate / Milvus。
>
> **换数据库**：回到项目根目录，`cd weaviate-demo` 或 `cd milvus-demo`，重复步骤 2-3。模型已下过，无需重复。

---

## Web UI

每个子项目都内置了 **FastAPI Web 应用**，可以在浏览器里直接写数据、做搜索：

```bash
# 先确保 docker compose up -d 已执行
cd qdrant-demo
source ../.venv/bin/activate    # 或进入对应子项目的虚拟环境
uvicorn src.app:app --reload --port 8888
```

| 子项目 | 端口 | 搜索页 | 写入页 | API 文档 |
|---|---|---|---|---|
| qdrant-demo | 8888 | <http://localhost:8888> | <http://localhost:8888/ingest> | <http://localhost:8888/docs> |
| weaviate-demo | 8889 | <http://localhost:8889> | <http://localhost:8889/ingest> | <http://localhost:8889/docs> |
| milvus-demo | 8890 | <http://localhost:8890> | <http://localhost:8890/ingest> | <http://localhost:8890/docs> |

### Makefile 快捷命令

每个子项目都提供了 `Makefile`，无需手记 uvicorn 参数：

```bash
cd qdrant-demo

make help          # 查看所有可用命令
make install       # pip install -r requirements.txt
make web           # 启动 Web UI（uvicorn --reload）
make start         # docker compose up -d
make stop          # docker compose down
make ingest        # 写入 10 条英文示例数据
make ingest-large  # 写入 100 条大数据集
make ingest-zh     # 写入中文示例数据
make search        # 交互式命令行搜索
make filter        # 带元数据过滤的命令行搜索
make logs          # 查看容器日志
make ps            # 查看容器状态
make clean         # 停止容器并删除数据卷（⚠️ 数据清空）
```

三个子项目的 Makefile 命令完全相同，端口号不同（8888 / 8889 / 8890）。

### 示例数据一键加载

写入页（`/ingest`）提供两个快速加载按钮，无需手动粘贴数据：

- **英文示例数据**：加载 `data/sample_en.json`（10 条，含 geography / technology / food 分类）
- **中文示例数据**：加载 `data/sample_zh.json`（10 条，覆盖历史、科技、食物等话题）

点击后通过 `GET /api/samples/{lang}` 接口拉取并填充文本框，再点"写入向量库"即可。

> **注意切换语言时要同步切换嵌入模型**：英文用 `all-MiniLM-L6-v2`（384 维），中文用 `bge-small-zh-v1.5`（512 维）。两种模型维度不同，切换后必须清空集合重建（`make clean` 后重新 `make ingest`）。**不需要重新配置 Docker**。

### 健康检查端点

每个应用都提供 `/health` 端点，返回数据库连接状态：

```bash
curl http://localhost:8888/health
# 正常：{"status":"ok","db":"qdrant"}
# 异常：HTTP 503, {"detail":"向量数据库未连接，请先执行 docker compose up -d..."}
```

Web UI 在数据库未启动时会显示友好提示，而不是直接报 500 错误。

---

## API 接口说明

所有三个子项目提供相同的 REST API（路径和参数完全一致）。

### POST /api/ingest — 写入数据

```bash
curl -X POST http://localhost:8888/api/ingest \
  -H "Content-Type: application/json" \
  -d '{"texts": ["巴黎是法国的首都", "向量数据库用于语义检索"]}'
```

**请求体：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `texts` | `string[]` | 要写入的文本列表，每条独立向量化 |

**响应：**

```json
{ "inserted": 2, "ids": [11, 12] }
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `inserted` | `int` | 实际写入的条数（空行自动跳过） |
| `ids` | `int[]` | 自动分配的 ID（从现有最大 ID + 1 起递增） |

### POST /api/search — 语义搜索

```bash
curl -X POST http://localhost:8888/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "法国著名地标", "limit": 5}'
```

**请求体：**

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `query` | `string` | 必填 | 查询文本 |
| `limit` | `int` | `5` | 返回条数，最大 20 |

**响应：**

```json
{
  "query": "法国著名地标",
  "results": [
    { "id": 1, "text": "巴黎是法国的首都", "score": 0.8732 },
    { "id": 3, "text": "埃菲尔铁塔建于1889年", "score": 0.8104 }
  ]
}
```

`score` 为余弦相似度，越接近 1 越相似（Weaviate 返回 0~1，Qdrant / Milvus 返回 -1~1）。

### GET /api/samples/{lang} — 获取示例文本

```bash
curl http://localhost:8888/api/samples/en    # 返回英文示例
curl http://localhost:8888/api/samples/zh    # 返回中文示例
```

**响应：**

```json
{ "lang": "en", "texts": ["Paris is the capital of France", ...] }
```

---

## 带元数据过滤的检索

每个子项目都提供 `src/filter_search.py`，演示向量搜索 + 分类过滤组合使用：

```bash
python -m src.filter_search   # 或 make filter
```

三库过滤语法对比：

| 向量库 | 过滤写法 |
|---|---|
| **Qdrant** | `Filter(must=[FieldCondition(key="category", match=MatchValue(value="technology"))])` |
| **Weaviate** | `Filter.by_property("category").equal("technology")` |
| **Milvus** | `filter='category == "technology"'` |

详细对比见 [`COMPARE.md`](./COMPARE.md)。

---

## 性能基准测试

`scripts/benchmark.py` 对三个库执行插入和查询性能测试（1000 条数据，100 次查询）：

```bash
python scripts/benchmark.py all       # 测试全部三个库
python scripts/benchmark.py qdrant    # 仅测试 Qdrant
python scripts/benchmark.py weaviate
python scripts/benchmark.py milvus
```

**输出示例：**

```
=== Qdrant ===
Insert: 1000 records in 4.23s (236.4 QPS)
Query:  avg 12.3ms, 81.3 QPS
Memory: +42MB
```

> 运行前需确保对应的 Docker 容器已启动。安装 `psutil` 可获得内存统计，否则跳过内存报告。

---

## 示例数据集

| 文件 | 条数 | 语言 | 说明 |
|---|---|---|---|
| `data/sample_en.json` | 10 | 英文 | 覆盖 geography / technology / food |
| `data/sample_zh.json` | 10 | 中文 | 覆盖历史、科技、食物等话题 |
| `data/sample_large_en.json` | 100 | 英文 | 8 个分类（technology / science / geography / history / food / sports / art / nature），ID 从 101 起，适合演示过滤检索 |

通过 Web UI 写入的自定义数据会追加到 `data/user_data.json`（本地备份，已加入 `.gitignore`，不会进仓库）。

---

## 嵌入模型

在各子项目的 `.env` 里通过 `EMBEDDING_MODEL` 切换：

| 模型 | 适用 | 维度 | 大小 |
|---|---|---|---|
| `sentence-transformers/all-MiniLM-L6-v2` | 英文 / 多语言 | 384 | ~90MB |
| `BAAI/bge-small-zh-v1.5` | 中文 | 512 | ~95MB |

> ⚠️ **换模型后维度会变**，已建好的 collection 必须删掉重建。执行 `make clean` 清空数据卷，再 `make ingest` 重新入库。**不需要重新配置 Docker**，Docker 只负责运行数据库进程，不感知向量维度。

模型缓存到项目内的 **`./models/`** 目录，三个子项目共用，不会进 Git。

**国内网络：**

```bash
export HF_ENDPOINT=https://hf-mirror.com      # 当前终端生效
echo 'export HF_ENDPOINT=https://hf-mirror.com' >> ~/.zshrc  # 永久生效
```

---

## Docker 安装与配置

> 已装好 Docker 可跳过本节，直接看[三者对比速查](#三者对比速查)。

### 安装 Docker

**macOS / Windows — 推荐 Docker Desktop**

前往 [https://docs.docker.com/get-docker/](https://docs.docker.com/get-docker/) 下载安装：

| 平台 | 说明 |
|---|---|
| macOS (Apple Silicon) | 下载 `.dmg`，拖到 Applications |
| macOS (Intel) | 同上，选 Intel 版本 |
| Windows 10/11 | 下载 `.exe`，按向导安装（需要 WSL 2，安装器会自动提示） |

安装后启动 Docker Desktop，等待图标变为**绿色（Running）**状态。

**Linux (Ubuntu / Debian)**

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker
sudo apt-get install -y docker-compose-plugin
```

**Linux (CentOS / RHEL)**

```bash
sudo yum install -y yum-utils
sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

验证：

```bash
docker --version && docker compose version
docker run hello-world
```

### 为 Milvus 调大 Docker 内存

Milvus 需要同时运行三个容器（etcd + minio + milvus），内存不够会导致反复重启（Exit 137 = OOM Kill）：

| 子项目 | 最低内存 | 推荐 |
|---|---|---|
| Qdrant | 1 GB | 2 GB |
| Weaviate | 1 GB | 2 GB |
| **Milvus** | **4 GB** | **6 GB** |

**macOS / Windows (Docker Desktop)**：Settings → Resources → Advanced → Memory 调到 ≥4GB → Apply & Restart。

**Linux**：默认无限制，确保宿主机可用内存够用（`free -h` 查看）。

### 配置 Docker 镜像加速（国内用户）

**macOS / Windows (Docker Desktop)**：Settings → Docker Engine → 加入：

```json
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://dockerproxy.com"
  ]
}
```

点 Apply & Restart。

**Linux：**

```bash
sudo tee /etc/docker/daemon.json > /dev/null <<'EOF'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://dockerproxy.com"
  ]
}
EOF
sudo systemctl daemon-reload && sudo systemctl restart docker
```

验证：`docker info | grep -A 5 "Registry Mirrors"`

### Docker 常用命令

```bash
docker compose ps                                              # 查看容器状态
docker compose logs -f <服务名>                                # 实时查看日志
docker compose up -d                                           # 后台启动
docker compose down                                            # 停止（保留数据）
docker compose down -v                                         # ⚠️ 停止并清空数据卷
docker compose pull && docker compose up -d --force-recreate  # 更新镜像
docker exec -it sandbox-qdrant sh                              # 进入容器调试
```

---

## 服务器部署

> 本项目默认面向本地学习场景。如需部署到服务器（让团队远程访问），参考以下步骤。

### 基础部署

1. 确保服务器已安装 Docker Compose v2、Python 3.10+。
2. 克隆项目并按[快速上手](#快速上手)完成模型下载和依赖安装。
3. 后台运行 uvicorn：

```bash
# nohup 简单后台运行
nohup uvicorn src.app:app --host 0.0.0.0 --port 8888 > app.log 2>&1 &
echo $! > app.pid

# 停止
kill $(cat app.pid)
```

### systemd 服务（推荐）

以 qdrant-demo 为例，创建 `/etc/systemd/system/qdrant-demo.service`：

```ini
[Unit]
Description=Qdrant Demo Web UI
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=<your-user>
WorkingDirectory=/path/to/semantic-sandbox/qdrant-demo
Environment="PATH=/path/to/semantic-sandbox/.venv/bin:/usr/local/bin:/usr/bin"
ExecStart=/path/to/semantic-sandbox/.venv/bin/uvicorn src.app:app --host 0.0.0.0 --port 8888
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now qdrant-demo
sudo systemctl status qdrant-demo
journalctl -u qdrant-demo -f          # 查看日志
```

### Nginx 反向代理

不建议直接暴露 uvicorn 端口，用 Nginx 做反向代理：

```nginx
server {
    listen 80;
    server_name your-domain.com;   # 或服务器公网 IP

    location / {
        proxy_pass http://127.0.0.1:8888;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 60s;
    }
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

如需 HTTPS，用 Certbot 自动申请证书：

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

### 防火墙与安全

```bash
# 只对外开放 80/443，不暴露向量数据库端口
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

> ⚠️ **注意事项**：
> - Qdrant（6333）、Weaviate（8080）、Milvus（19530）端口**不要对外暴露**，默认无鉴权。
> - Web UI 目前也无鉴权，建议加 Nginx Basic Auth 或放到内网 / VPN 后面。
> - 数据持久化在 Docker Volume，可用 `docker volume ls` 查看，定期备份。

### 健康监控

```bash
# 手动检查
curl http://localhost:8888/health

# crontab 自动监控（每 5 分钟）
*/5 * * * * curl -sf http://localhost:8888/health || systemctl restart qdrant-demo
```

---

## 三者对比速查

| 项 | Qdrant | Weaviate | Milvus |
|---|---|---|---|
| 本地容器数 | 1 | 1 | 3（etcd + minio + milvus） |
| 最低内存 | 1 GB | 1 GB | 4 GB |
| 启动时间 | ~3s | ~5s | ~30s |
| Python 客户端 | `qdrant-client` | `weaviate-client` v4 | `pymilvus` |
| 额外字段存储 | Payload（无 schema） | Properties（需提前定义） | Dynamic field（需开启） |
| 过滤语法 | FieldCondition 对象 | Filter 链式调用 | SQL-like 字符串 |
| score 含义 | 余弦相似度（-1~1） | 1 - cosine_distance（0~1） | 余弦相似度（-1~1） |
| 写入后可见 | 立即 | 立即（异步索引） | 需 `load_collection()` |
| 推荐入门顺序 | ★★★ 先学这个 | ★★☆ | ★☆☆ 最复杂 |

完整三库 API 横向对比（建集合 / 写入 / 搜索 / 过滤 / 删除）见 [`COMPARE.md`](./COMPARE.md)。

---

## 目录结构

```
semantic-sandbox/
├── README.md                 ← 你正在读的这个
├── COMPARE.md                ← 三库 API 横向对比（三列并排代码块）
├── .gitignore
├── data/
│   ├── sample_en.json        ← 10 条英文示例数据（含 category 字段）
│   ├── sample_zh.json        ← 10 条中文示例数据
│   ├── sample_large_en.json  ← 100 条英文数据，8 个分类，供过滤检索演示
│   └── user_data.json        ← Web UI 写入的数据备份（.gitignore，本地生成）
├── scripts/
│   ├── preload_model.py      ← 预下载嵌入模型到 ./models/
│   └── benchmark.py          ← 三库插入/查询性能横向对比
├── qdrant-demo/              ← Qdrant 子项目（端口 8888）
│   ├── Makefile
│   ├── src/
│   │   ├── app.py            ← FastAPI Web UI + REST API
│   │   ├── ingest.py         ← 命令行批量入库
│   │   ├── search.py         ← 命令行语义搜索
│   │   └── filter_search.py  ← 带元数据过滤的搜索
│   └── templates/            ← Jinja2 HTML 模板
├── weaviate-demo/            ← Weaviate 子项目（端口 8889）
└── milvus-demo/              ← Milvus 子项目（端口 8890）
```

---

## 目录读图建议

建议按以下顺序阅读代码：

1. `data/sample_en.json` — 看数据结构（id / text / category）
2. `qdrant-demo/src/embedder.py` — 文本如何变成向量
3. `qdrant-demo/src/ingest.py` — 向量如何入库
4. `qdrant-demo/src/search.py` — 查询如何做
5. `qdrant-demo/src/filter_search.py` — 加上元数据过滤
6. `qdrant-demo/src/app.py` — Web UI 和 REST API 如何组织
7. 对比阅读 `weaviate-demo/` 和 `milvus-demo/`，找不同点
8. 查阅 `COMPARE.md` 做系统性横向对比

---

## 常见问题

**Q: 第一次跑脚本为什么很慢？**
A: 两个原因之一：① 正在下载嵌入模型（先跑 `python scripts/preload_model.py` 可以提前下好）；② `pip install` 在下载 PyTorch（约 1-2GB），等这一次，后面都快。

**Q: HuggingFace 下载超时或报 `ConnectionError`？**
A: `export HF_ENDPOINT=https://hf-mirror.com`，然后重跑命令。建议写进 `~/.zshrc` 永久生效。

**Q: 切换了嵌入模型（中英文），需要重新配置 Docker 吗？**
A: **不需要**。Docker 只负责运行向量数据库进程，不感知嵌入模型。但向量维度会变（384 → 512），已有的 collection 必须删掉重建。执行 `make clean` 清空 Docker 数据卷，再 `make ingest` 重新入库即可。

**Q: Docker 启动 Milvus 失败 / 容器反复重启？**
A: 八成是内存不够（Exit Code 137 = OOM Kill）。Docker Desktop 默认内存偏小，调到 ≥4GB 再试：Settings → Resources → Advanced → Memory。

**Q: `docker compose` 提示命令不存在？**
A: 装的可能是老版 Compose v1（`docker-compose`，有连字符）。本项目用 v2，Ubuntu 执行 `sudo apt-get install docker-compose-plugin` 升级。

**Q: 拉镜像超时或 `connection refused`？**
A: 国内访问 Docker Hub 不稳定，参考[配置 Docker 镜像加速](#配置-docker-镜像加速国内用户)。

**Q: Web UI 显示"向量数据库未连接"？**
A: 先执行 `docker compose up -d`，然后 `docker compose ps` 确认容器状态为 `running`（Milvus 首次启动约需 30 秒）。也可用 `curl http://localhost:8888/health` 检查。

**Q: `user_data.json` 出现在 `git status` 里？**
A: 已在 `.gitignore` 里配置忽略 `data/user_data.json`。如果文件已被追踪，执行 `git rm --cached data/user_data.json` 取消追踪即可。

**Q: 代码里为什么没有密码 / API Key？**
A: 本地 Docker 起的服务默认无鉴权，仅供学习。生产环境必须开启认证，参考[服务器部署 → 防火墙与安全](#防火墙与安全)。

---

## License

[MIT](./LICENSE) — 随便改、随便用。
