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
A: 八成是内存不够。Docker Desktop 默认内存偏小，把资源调到 ≥4GB 再试。

**Q: 代码里怎么都没写密码 / API Key？**
A: 本地 Docker 起的服务默认没开鉴权，仅供学习。生产环境必须开启认证，各子项目 README 的"生产注意事项"有说明。

**Q: 为什么 `venv/`、`.env` 没在仓库里？**
A: 它们在 `.gitignore` 里，你本地需要自己建。`requirements.txt` 和 `.env.example` 是会提交的。

---

## License

[MIT](./LICENSE) — 随便改、随便用。
