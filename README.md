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

## 快速开始（以 Qdrant 为例，**推荐最先跑这个**，最轻量）

```bash
# 1) 克隆后进入项目
cd semantic-sandbox

# 2) 复制公共配置（选嵌入模型）
cp .env.example .env

# 3) 预下载嵌入模型（约 185MB，一次搞定，三个子项目共用）
python3 -m venv .venv && source .venv/bin/activate

# ⚠️ 首次 pip install 会顺带装 PyTorch（sentence-transformers 的依赖），约 1-2GB，要等几分钟
pip install sentence-transformers python-dotenv

# 🇨🇳 国内网络访问 HuggingFace 慢/不通时，先 export 这个再运行 preload：
# export HF_ENDPOINT=https://hf-mirror.com
python scripts/preload_model.py

# 4) 进入 qdrant 子项目，按它的 README 继续
cd qdrant-demo
cat README.md
```

> 为什么推荐 Qdrant 先跑：单容器、启动最快、资源占用最小。熟悉流程后再试 Weaviate 和 Milvus。

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

模型默认缓存到 `~/.cache/huggingface/`，是**用户级缓存**，三个子项目天然共享，不会重复下载。

**国内网络提示**：HuggingFace 直连经常超时。用镜像站（放在 shell 配置里一劳永逸）：
```bash
# 加到 ~/.zshrc 或 ~/.bashrc
export HF_ENDPOINT=https://hf-mirror.com
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
