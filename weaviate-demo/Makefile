# Weaviate Demo — 常用命令
# 用法：make <target>   （在 weaviate-demo/ 目录下执行）

PYTHON   = python3
UVICORN  = uvicorn
WEB_PORT = 8889

.PHONY: help install start stop clean \
        ingest ingest-large ingest-zh \
        search filter web logs ps

help:
	@printf "\n\033[1mWeaviate Demo 可用命令\033[0m\n\n"
	@printf "  \033[36mmake install\033[0m       安装 Python 依赖\n"
	@printf "  \033[36mmake start\033[0m         启动 Weaviate 容器\n"
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
	docker compose up -d
	@echo "Weaviate 启动中（约 5 秒），健康检查：curl http://localhost:8080/v1/.well-known/ready"

stop:
	docker compose down

clean:
	docker compose down -v
	@echo "数据已清除"

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
	@docker compose ps --status running 2>/dev/null | grep -q "running" || \
		printf "\033[33m提示：数据库容器未运行，请先执行 make start\033[0m\n"
	$(UVICORN) src.app:app --reload --port $(WEB_PORT)

logs:
	docker compose logs -f weaviate

ps:
	docker compose ps
