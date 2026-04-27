# Qdrant Service — 常用命令
# 用法：make <target>   （在 qdrant-service/ 目录下执行）

PYTHON   = python3
UVICORN  = uvicorn
WEB_PORT = 8888
COMPOSE  = docker compose -f ../docker-compose.yml --profile qdrant

.PHONY: help install start stop clean \
        init-db ingest ingest-large ingest-zh \
        search filter web logs ps

help:
	@printf "\n\033[1mQdrant Service 可用命令\033[0m\n\n"
	@printf "  \033[36mmake install\033[0m       安装 Python 依赖\n"
	@printf "  \033[36mmake start\033[0m         启动 PostgreSQL + Qdrant 容器\n"
	@printf "  \033[36mmake init-db\033[0m       初始化 PostgreSQL 表结构\n"
	@printf "  \033[36mmake stop\033[0m          停止容器（保留数据）\n"
	@printf "  \033[36mmake clean\033[0m         停止容器并删除数据\n"
	@printf "  \033[36mmake ingest\033[0m        入库（英文示例 10 条）\n"
	@printf "  \033[36mmake ingest-large\033[0m  入库（大数据集 100 条）\n"
	@printf "  \033[36mmake ingest-zh\033[0m     入库（中文示例数据）\n"
	@printf "  \033[36mmake search\033[0m        命令行交互式语义搜索\n"
	@printf "  \033[36mmake filter\033[0m        命令行带分类过滤搜索\n"
	@printf "  \033[36mmake web\033[0m           启动 Web UI  http://localhost:$(WEB_PORT)\n"
	@printf "  \033[36mmake logs\033[0m          实时查看容器日志\n"
	@printf "  \033[36mmake ps\033[0m            查看容器状态\n\n"

install:
	pip install -r requirements.txt

start:
	$(COMPOSE) up -d postgres qdrant
	@echo "Qdrant 启动中，Web 控制台：http://localhost:6333/dashboard"

stop:
	$(COMPOSE) down

clean:
	$(COMPOSE) down -v
	@echo "数据已清除"

init-db:
	$(PYTHON) ../scripts/init_postgres.py

ingest:
	$(PYTHON) -m src.ingest

ingest-large:
	$(PYTHON) -m src.ingest ../data/sample_large_en.json

ingest-zh:
	$(PYTHON) -m src.ingest ../data/sample_zh.json

search:
	$(PYTHON) -m src.search

filter:
	$(PYTHON) -m src.filter_search

web:
	@$(COMPOSE) ps --status running 2>/dev/null | grep -q "postgres" || \
		printf "\033[33m提示：PostgreSQL / Qdrant 容器未运行，请先执行 make start\033[0m\n"
	$(UVICORN) src.app:app --reload --port $(WEB_PORT)

logs:
	$(COMPOSE) logs -f postgres qdrant

ps:
	$(COMPOSE) ps
