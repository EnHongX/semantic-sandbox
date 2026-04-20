# qdrant-demo

用 [Qdrant](https://qdrant.tech/) 实现的"入库 + 语义检索"示例。**推荐作为三者中的第一个练习**：单容器、启动最快、资源占用最小。

---

## 目录结构

```
qdrant-demo/
├── README.md
├── docker-compose.yml     启动 Qdrant 服务
├── requirements.txt       Python 依赖
├── .env.example           环境变量模板
└── src/
    ├── config.py          读取 .env
    ├── embedder.py        文本 → 向量（sentence-transformers）
    ├── ingest.py          读取 JSON 数据 → 入库
    └── search.py          交互式检索
```

---

## 一步步跑起来

### 1. 启动 Qdrant

```bash
cd qdrant-demo
docker compose up -d

# 验证
docker compose ps
curl http://localhost:6333/readyz     # 返回 "all shards are ready"
```

Web 控制台（可以直接看 collection 和数据）：<http://localhost:6333/dashboard>

### 2. 装 Python 依赖

**强烈建议用虚拟环境**，免得污染全局 Python：

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

> ⚠️ 首次安装会顺带拉 PyTorch（`sentence-transformers` 的依赖），约 **1-2GB**，需要几分钟。没卡死，耐心等。
>
> 🇨🇳 国内 HuggingFace 下载慢可以先 `export HF_ENDPOINT=https://hf-mirror.com`，再跑后面的 ingest / search。

### 3. 配置环境变量

```bash
cp .env.example .env
```

默认用英文模型 + 英文数据，开箱即用。要用中文：

```bash
# 编辑 .env，把两行改成：
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
DATA_FILE=../data/sample_zh.json
```

### 4. 入库

```bash
python -m src.ingest
```

看到类似输出：
```
[ingest] 读取数据: .../data/sample_en.json
[embedder] 加载模型: sentence-transformers/all-MiniLM-L6-v2
[ingest] 创建集合 sandbox_docs (维度=384, 距离=cosine)
[ingest] 写入 10 条 → sandbox_docs
[ingest] 完成。集合中共有 10 条。
```

### 5. 搜索

交互式：

```bash
python -m src.search
```

```
> where is the eiffel tower
查询: where is the eiffel tower
------------------------------------------------------------
1. score=0.7432  id=1
   The Eiffel Tower is a wrought-iron lattice tower located in Paris, France.
2. score=0.2105  id=3
   The Great Wall of China stretches for thousands of miles across northern China.
...
```

单次查询：
```bash
python -m src.search "what is a vector database"
```

---

## 换数据 / 换模型

### 换数据

数据文件就是一个 JSON 数组，每条记录有 `id`（整数）和 `text`（字符串）：

```json
[
  {"id": 1, "text": "你的第一条数据"},
  {"id": 2, "text": "你的第二条数据"}
]
```

把你的文件放到任意位置，然后：
```bash
python -m src.ingest /path/to/your_data.json
```
或者改 `.env` 里的 `DATA_FILE`。

### 换模型

改 `.env` 的 `EMBEDDING_MODEL`。**然后必须删掉老集合**（维度不同会报错）：

```bash
curl -X DELETE http://localhost:6333/collections/sandbox_docs
python -m src.ingest
```

---

## 代码里这些概念对应什么

| 代码 | Qdrant 里的概念 |
|---|---|
| `client.create_collection` | 建集合，指定向量维度和距离度量 |
| `qm.Distance.COSINE` | 余弦相似度；因为向量做了归一化，等价于内积 |
| `qm.PointStruct(id, vector, payload)` | 一条记录：id + 向量 + 附加字段（payload） |
| `client.upsert` | 插入或更新（按 id） |
| `client.search` | 给一个向量，返回 top-k 最近邻 |
| `payload` | 类似 MongoDB 的文档，存业务字段 |

---

## 停止和清理

```bash
docker compose down           # 停止容器但保留数据
docker compose down -v        # 连数据一起删
rm -rf qdrant_data/           # 手动删本地数据目录
```

---

## 常见问题

**Q: `Connection refused` / 连不上 6333**
A: 容器没起来，先 `docker compose ps`。如果 `Exit` 了看 `docker compose logs qdrant`。

**Q: 换了中文模型后 ingest 报错**
A: 错误信息里会提示你删集合的命令，照着执行再 ingest 一次。

**Q: `search` 结果里 score 都很低？**
A: 说明库里没有和查询语义相近的内容。英文查询配英文数据、中文查询配中文数据，别混用。

---

## 生产注意事项（学完可忽略）

- 开启 API Key：在 docker-compose 里加环境变量 `QDRANT__SERVICE__API_KEY=...`，客户端连接时传 `api_key=...`
- 数据盘用 SSD、做好备份
- 并发写入用批量 `upsert`，单条 upsert 有 RPC 开销
- 大数据量下开启 HNSW 索引调优（`hnsw_config`）
