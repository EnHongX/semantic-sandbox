# semantic-sandbox

一个用来**动手学习向量数据库**的练习项目：同一份数据，分别用 **Milvus / Weaviate / Qdrant** 三套主流向量库各自实现一次"入库 + 语义检索"的完整流程。

目标读者：**有约一年 Python 经验、第一次接触向量数据库**的开发者。

---

## 整体流程（一张图理解向量检索）

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

- **嵌入模型**（embedding model）：把文字映射成固定长度的向量，语义相近的文字 → 向量也相近
- **向量数据库**：专门解决"在海量向量里快速找近邻"这个问题（暴力遍历太慢，要建索引）
- **相似度**：常见的是余弦相似度（cosine），值越大越相似

本项目把上面这套流程用三种向量库各实现一遍，让你对比它们的 API 差异。

---

## 项目由两部分组成（重要！）

很多新手以为 `docker compose up -d` 把容器起起来项目就能跑了。**不是**。这个项目实际上有**两个独立的组件**，两个都要准备好：

```
  ┌─────────────────────────────┐        ┌─────────────────────────────┐
  │ 组件 A：向量数据库            │        │ 组件 B：嵌入模型              │
  │ (跑在 Docker 容器里)          │        │ (跑在你本机 Python 里)         │
  │                             │        │                             │
  │ Qdrant / Weaviate / Milvus   │        │ sentence-transformers +      │
  │ 存向量、建索引、做检索         │        │ 下载下来的模型权重文件         │
  │                             │        │ 负责：文字 → 向量             │
  │ 通过 docker compose 启动      │        │ 通过 pip install + 下载模型   │
  └─────────────────────────────┘        └─────────────────────────────┘
              ▲                                         │
              │   ingest.py 把向量写进去  ◄──────────────┘
              │   search.py 拿查询向量去搜
```

**为什么分成两部分？** 向量数据库本身不懂文字，只认向量。把文字变成向量的活儿（嵌入）通常由应用层（Python 代码 + 模型）完成。这种架构让你可以随意换模型，数据库不用改。

---

## 三步部署（完整流程）

```bash
# ─── 步骤 1：准备组件 B（嵌入模型）────────────────────────────────
cd semantic-sandbox
python3 -m venv .venv && source .venv/bin/activate

# 🇨🇳 国内网络先跑这行再继续（跳过 HuggingFace 官方站点直连）
# export HF_ENDPOINT=https://hf-mirror.com

pip install sentence-transformers python-dotenv       # 会顺带装 PyTorch，约 1-2GB，几分钟
python scripts/preload_model.py                        # 下载两个模型（约 185MB），缓存到 ./models/

# ─── 步骤 2：准备组件 A（向量数据库，以 qdrant 为例）─────────────
cd qdrant-demo
cp .env.example .env
docker compose up -d                                   # 启动数据库容器
pip install -r requirements.txt                        # 装 qdrant 客户端

# ─── 步骤 3：跑业务代码（入库 + 搜索）─────────────────────────────
python -m src.ingest                                   # 文本 → 向量 → 写入数据库
python -m src.search                                   # 交互式语义搜索
```

**想换个数据库？** 回到项目根目录，`cd weaviate-demo` 或 `cd milvus-demo`，重复步骤 2-3 即可。组件 B（模型）已经下过了，不用再下。

> **为什么推荐从 Qdrant 开始？** 单容器、启动最快（约 3 秒）、内存占用最小（≥1GB 就行）。流程跑通后再试 Weaviate 和 Milvus，对比三者 API 差异。

> **关于模型缓存**：本项目把模型下载到**项目内的 `./models/` 目录**（不是系统级的 `~/.cache/huggingface/`），好处是：
> - 模型"跟项目走"，拷贝项目目录到别的机器，模型一起带过去，不用重新下载
> - 多个虚拟环境都用同一份模型，不会重复占盘
> - 三个子项目共用这一份缓存
>
> 但 `models/` 目录在 `.gitignore` 里，**不会提交到 GitHub**（单文件就超 GitHub 100MB 上限，也不该进 Git）。新克隆仓库的人需要自己跑一次 `preload_model.py`。

---

## Web UI 快速上手

每个子项目都内置了一个 **FastAPI Web 应用**，不需要在命令行里敲命令，打开浏览器就能写数据、做搜索。

```bash
# 以 qdrant-demo 为例（先确保 docker compose up -d 已跑）
cd qdrant-demo
source .venv/bin/activate
uvicorn src.app:app --reload --port 8888
```

| 子项目 | 默认端口 | 搜索页 | 写入页 | API 文档 |
|---|---|---|---|---|
| qdrant-demo | 8888 | <http://localhost:8888> | <http://localhost:8888/ingest> | <http://localhost:8888/docs> |
| weaviate-demo | 8889 | <http://localhost:8889> | <http://localhost:8889/ingest> | <http://localhost:8889/docs> |
| milvus-demo | 8890 | <http://localhost:8890> | <http://localhost:8890/ingest> | <http://localhost:8890/docs> |

每个子项目的 README 里有完整的 API 接口说明（请求格式、响应格式、curl 示例）。

---

## 这个项目解决什么问题

向量数据库的官方文档通常各写各的，术语不统一（Milvus 叫 *collection*，Weaviate 叫 *class/collection*，Qdrant 也叫 *collection* 但字段叫 *payload*），新手很容易被细节劝退。

本项目让你：

1. **本地一键跑起来**：每个子项目都配 `docker-compose.yml`，`docker compose up -d` 就能启动数据库服务。
2. **三套 API 横向对比**：同样的"建库 → 入库 → 搜索"三个脚本，看三个库写法的差异。
3. **中英文都能玩**：内置英文和中文两份示例数据，配套两个嵌入模型（英文用 MiniLM、中文用 bge-small-zh），改一个环境变量就能切换。
4. **直观看到效果**：`search.py` 是交互式命令行，输入一句话，立刻看到最相近的几条结果和相似度分数。

---

## 目录结构

```
semantic-sandbox/
├── README.md                 ← 你正在读的这个
├── .env.example              ← 公共配置模板（嵌入模型）
├── .gitignore
├── data/                     ← 示例数据（中英文各一份）
│   ├── sample_en.json
│   └── sample_zh.json
├── scripts/
│   └── preload_model.py      ← 预下载嵌入模型
├── milvus-demo/              ← Milvus 子项目（独立可运行）
├── weaviate-demo/            ← Weaviate 子项目
└── qdrant-demo/              ← Qdrant 子项目
```

每个子项目都是**独立可运行**的：自带 `README.md`、`docker-compose.yml`、`requirements.txt`、`.env.example` 和 `src/`，想学哪个进哪个目录就行。

---

## 前置要求

| 工具 | 版本 | 说明 |
|---|---|---|
| Python | 3.10+ | 建议用 `venv` 创建虚拟环境 |
| Docker | 20+ | 用来启动向量库服务；**Milvus 要求至少 4GB 内存** |
| Docker Compose | v2 | 现在是 `docker compose`（中间空格），不是老的 `docker-compose` |

检查一下：

```bash
python3 --version
docker --version
docker compose version
```

---

## Docker 安装与配置

> 已经装好 Docker 的可跳过本节，直接看[三者对比速查](#三者对比速查)。

### 安装 Docker

**macOS / Windows — 推荐 Docker Desktop**

前往 [https://docs.docker.com/get-docker/](https://docs.docker.com/get-docker/) 下载对应版本：

| 平台 | 说明 |
|---|---|
| macOS (Apple Silicon / M 系列) | 下载 `.dmg`，双击安装，拖到 Applications |
| macOS (Intel) | 同上，选 Intel 版本 |
| Windows 10/11 | 下载 `.exe`，按向导安装；需要 WSL 2（安装器会自动提示） |

安装后启动 Docker Desktop，等待菜单栏 / 任务栏图标变为 **绿色（Running）** 状态。

**Linux (Ubuntu / Debian)**

```bash
# 使用官方一键安装脚本
curl -fsSL https://get.docker.com | sh

# 把当前用户加入 docker 组，避免每次都要 sudo
sudo usermod -aG docker $USER
newgrp docker          # 或重新登录终端使生效

# 安装 Compose v2 插件（Ubuntu 22.04+ 通常已自带）
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

安装完后统一验证：

```bash
docker --version          # Docker version 26.x.x ...
docker compose version    # Docker Compose version v2.x.x
docker run hello-world    # 能看到 "Hello from Docker!" 说明一切正常
```

> **v1 vs v2**：本项目用 `docker compose`（空格，Compose v2），不是老的 `docker-compose`（连字符，v1）。如果运行 `docker compose version` 报错，说明还是 v1，需要升级或安装 Compose v2 插件。

---

### 为 Milvus 调大 Docker 内存

Milvus 需要同时运行三个容器（etcd + minio + milvus），**内存不够会导致容器反复重启**（Exit Code 137 = 被系统 OOM Kill）。

各子项目内存要求：

| 子项目 | 最低内存 | 推荐 |
|---|---|---|
| Qdrant | 1 GB | 2 GB |
| Weaviate | 1 GB | 2 GB |
| **Milvus** | **4 GB** | **6 GB** |

**macOS / Windows (Docker Desktop)**：

1. 打开 Docker Desktop → 点右上角 ⚙️ Settings
2. 左侧选 **Resources → Advanced**
3. 把 **Memory** 滑块调到 ≥ 4 GB（只跑 Qdrant/Weaviate 的话 2 GB 够用）
4. 点右下角 **Apply & Restart**，等 Docker Desktop 重启完成

**Linux**：默认无内存上限（直接使用宿主机内存），确保宿主机可用内存满足上表即可。可以用 `free -h` 查看。

---

### 配置 Docker 镜像加速（国内用户）

国内从 Docker Hub 拉取镜像经常超时或限速。配置镜像加速器可以大幅提速：

**macOS / Windows (Docker Desktop)**：

1. 打开 Docker Desktop → Settings → **Docker Engine**
2. 在右侧 JSON 配置中加入 `registry-mirrors` 字段：

```json
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://dockerproxy.com"
  ]
}
```

3. 点 **Apply & Restart**

**Linux (`/etc/docker/daemon.json`)**：

```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json > /dev/null <<'EOF'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://dockerproxy.com"
  ]
}
EOF
sudo systemctl daemon-reload
sudo systemctl restart docker
```

验证镜像加速是否生效：

```bash
docker info | grep -A 5 "Registry Mirrors"
```

> **注意**：镜像加速器地址可能会失效或限速，如果某个地址不稳定，可以去 [https://status.daocloud.io](https://status.daocloud.io) 或搜索最新可用地址。

---

### Docker 常用命令速查

```bash
# 查看所有运行中的容器
docker ps

# 查看某个 compose 项目所有容器的状态（在子项目目录下执行）
docker compose ps

# 查看容器日志
docker compose logs qdrant          # 看指定服务的日志
docker compose logs -f milvus       # -f 实时跟踪

# 启动 / 停止
docker compose up -d                # 后台启动
docker compose down                 # 停止容器，保留数据卷
docker compose down -v              # ⚠️ 停止并删除数据卷（数据清空）

# 重新拉取最新镜像（镜像版本有更新时）
docker compose pull
docker compose up -d --force-recreate

# 进入容器内部（调试用）
docker exec -it sandbox-qdrant sh
```

---

## 三者对比速查

| 项 | Milvus | Weaviate | Qdrant |
|---|---|---|---|
| 本地启动 | 三个容器（etcd + minio + milvus） | 单容器 | 单容器 |
| 最低内存 | 4GB+ | 1GB | 1GB |
| 启动时间 | ~30s | ~5s | ~3s |
| Python 客户端 | `pymilvus` | `weaviate-client` v4 | `qdrant-client` |
| "表"叫什么 | Collection | Collection | Collection |
| 带结构化字段 | Schema + fields | Properties | Payload |
| 默认端口 | 19530 (gRPC) | 8080 (HTTP) | 6333 (HTTP) / 6334 (gRPC) |
| 学习曲线 | 中（概念最多） | 低 | 低 |

---

## 嵌入模型

两个模型在 `.env` 里通过 `EMBEDDING_MODEL` 切换：

| 模型 | 适用 | 维度 | 大小 |
|---|---|---|---|
| `sentence-transformers/all-MiniLM-L6-v2` | 英文/多语言 | 384 | ~90MB |
| `BAAI/bge-small-zh-v1.5` | 中文 | 512 | ~95MB |

> ⚠️ **换模型后维度会变**，已建好的 collection 必须删掉重建。每个子项目的 `ingest.py` 启动时会校验维度，不一致会报错提示。

模型缓存到项目内的 **`./models/`** 目录（不是系统级的 `~/.cache/huggingface/`），三个子项目共用这一份缓存。该目录已被 `.gitignore` 忽略，不会进仓库。

**国内网络提示**：HuggingFace 直连经常超时。用镜像站：
```bash
# 临时生效（当前终端）
export HF_ENDPOINT=https://hf-mirror.com

# 永久生效（加到 ~/.zshrc 或 ~/.bashrc）
echo 'export HF_ENDPOINT=https://hf-mirror.com' >> ~/.zshrc
```

---

## 目录读图建议

建议按以下顺序阅读代码：

1. `data/sample_en.json` — 看数据长什么样
2. `qdrant-demo/src/embedder.py` — 看文本如何变成向量
3. `qdrant-demo/src/ingest.py` — 看向量如何入库
4. `qdrant-demo/src/search.py` — 看查询如何做
5. 然后再看 `weaviate-demo/` 和 `milvus-demo/`，对比差异

---

## 常见问题

**Q: 第一次跑脚本为什么卡很久？**
A: 通常是两个原因之一：（1）在下载嵌入模型，运行过 `scripts/preload_model.py` 就能避免；（2）`pip install` 在下载 PyTorch（约 1-2GB），耐心等完这一次，后面都快。

**Q: HuggingFace 下载超时或报 `ConnectionError`？**
A: 设置镜像环境变量：`export HF_ENDPOINT=https://hf-mirror.com`，然后重跑命令。建议写进 shell 配置一劳永逸。

**Q: Docker 启动 Milvus 失败？**
A: 八成是内存不够。Docker Desktop 默认内存偏小，把资源调到 ≥4GB 再试（路径：Settings → Resources → Advanced → Memory）。

**Q: `docker compose` 提示命令不存在？**
A: 你装的可能是老版 Compose v1（`docker-compose`，有连字符）。本项目用 v2，参考上面"Docker 安装"一节升级。Linux 用 `sudo apt-get install docker-compose-plugin` 即可。

**Q: `docker compose up -d` 时拉镜像超时/报 `timeout` 或 `connection refused`？**
A: 国内访问 Docker Hub 不稳定。参考上面"配置 Docker 镜像加速"一节，配置国内镜像源后重试。

**Q: 代码里怎么都没写密码 / API Key？**
A: 本地 Docker 起的服务默认没开鉴权，仅供学习。生产环境必须开启认证，各子项目 README 的"生产注意事项"有说明。

**Q: 为什么 `venv/`、`.env` 没在仓库里？**
A: 它们在 `.gitignore` 里，你本地需要自己建。`requirements.txt` 和 `.env.example` 是会提交的。

---

## License

[MIT](./LICENSE) — 随便改、随便用。
