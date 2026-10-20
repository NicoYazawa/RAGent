# RAGent

[![CI](https://github.com/NicoYazawa/RAGent/actions/workflows/ci.yml/badge.svg)](https://github.com/NicoYazawa/RAGent/actions/workflows/ci.yml)

一个支持多知识库、混合检索和可回放决策链的 RAG 问答项目。前端使用 Vue 3，后端使用 FastAPI，通过 SSE 展示检索、纠正、生成与反思过程。

## 功能

- **知识库管理**：上传 Markdown、TXT、PDF、DOCX，完成解析、章节切片、向量化与索引；支持查看切片、失败重试和删除文档。
- **混合检索**：Elasticsearch 向量检索与 BM25 关键词检索，经应用层 RRF 融合，可选启用 Rerank 精排。
- **Agent 问答**：意图识别、查询改写与 HyDE、相关度评分、CRAG 纠正、Self-RAG 反思；另有闲聊和业务数据查询路径。
- **答案溯源**：引用编号与原文对应，使用文档 ID 和切片 UID 定位，避免同名文档混淆；反思重生成会替换旧答案。
- **多模态会话**：支持附图提问、多轮上下文、重新生成及停止输出。图片理解取决于当前模型的视觉能力。
- **诊断工具**：检索 Playground、决策日志回放与导出、依赖健康状态检查。
- **中英文界面**：支持切换界面语言；答案语言依据问题判断。

## 技术栈与流程

| 层次 | 实现 |
| --- | --- |
| 前端 | Vue 3、TypeScript、Vite、Pinia、Tailwind CSS、vue-i18n |
| 后端 | Python、FastAPI、Pydantic、HTTPX、SSE |
| 元数据 | MySQL 8：文档、切片、会话、数据源配置与决策日志 |
| 检索索引 | Elasticsearch 8：dense vector kNN、BM25；IK 不可用时回退 standard 分词器 |
| 模型接口 | OpenAI 兼容接口；适配器目录位于 `backend/app/providers/` |
| 部署与测试 | Docker Compose、Nginx、pytest、Ruff、Vitest、GitHub Actions |

文档入库：`上传 → 解析 → 切片 → Embedding → Elasticsearch + MySQL`。

知识问答：`意图识别 → 查询规划 → 双路检索 → RRF / 可选精排 → 评分 / 纠正 → 流式生成 → 反思 → 引用溯源`。

MySQL 保存元数据和切片正文，Elasticsearch 保存可重建的检索索引，原始上传文件保存在独立数据目录中。

## 使用 Docker Compose 启动

需要 Git、Docker 和 Docker Compose，以及可用的 LLM / Embedding 模型服务。

### 1. 克隆与配置

```bash
git clone https://github.com/NicoYazawa/RAGent.git
cd RAGent
```

复制根目录 `.env.example` 为 `.env`：

```bash
# macOS / Linux
cp .env.example .env
```

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

编辑 `.env`，至少填写 `DEEPSEEK_API_KEY` 和 `DASHSCOPE_API_KEY`，或者改用其他已适配的供应商。默认配置使用 DeepSeek 生成答案、百炼生成 1024 维向量。模型名称是本项目的配置默认值，请以自己的服务账号实际可用模型为准。

同时修改示例数据库口令，并保持 `MYSQL_PASSWORD` 与 `MYSQL_ROOT_PASSWORD` 一致。`.env` 已被 Git 忽略，不要将真实密钥提交到仓库。

### 2. 启动服务

```bash
docker compose up -d --build
docker compose ps
```

| 地址 | 用途 |
| --- | --- |
| `http://localhost` | Web 界面 |
| `http://localhost/api/health` | 后端依赖状态与索引一致性 |
| `127.0.0.1:3306` | MySQL，仅绑定宿主机回环地址 |
| `http://127.0.0.1:9200` | Elasticsearch，仅绑定宿主机回环地址 |

### 3. 初始化演示检索数据

`ragent_init.sql` 在 **MySQL 数据卷第一次初始化时** 自动导入，包含演示知识库切片、销售数据和历史会话。它不是纯空库建表脚本，也不会向新的 Elasticsearch 数据卷写入向量。

首次使用演示知识库时，配置好 Embedding 密钥后执行：

```bash
docker compose exec backend python -m scripts.backfill_es_from_mysql
```

该命令调用真实 Embedding 服务并产生相应费用，从 MySQL 切片重建 ES 索引。完成后检查 `/api/health` 中的 `status` 和 `consistency`。也可在界面中新建知识库，上传 `test_docs/` 中的文档体验完整入库流程。

初始化 SQL 内的历史上传路径和图片引用不代表当前卷中存在对应文件。需要原始文件或重试完整解析时，请重新上传文档。

### 日常操作

```bash
docker compose logs -f backend
docker compose logs -f es
docker compose down
```

普通 `down` 保留数据卷。`docker compose down -v` 会删除 MySQL、ES 和上传文件卷，仅在明确需要清空数据时使用。

## 本地开发

后端以 **Python 3.12** 为 CI 基准；前端需要 **Node.js 20.19+ 或 22.12+**，建议使用 Node.js 22。MySQL 和 ES 可使用已有实例，也可在配置根目录 `.env` 后运行 `docker compose up -d db es`。

### 后端

以下命令在项目根目录执行，先创建虚拟环境：

```bash
python -m venv .venv
```

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

安装依赖，并复制 `backend/.env.example` 为 `backend/.env`：

```bash
python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
```

本地后端读取 **`backend/.env`**；Compose 后端读取根目录 **`.env`**。两者是独立配置，不能互相替代。使用 Compose 的数据库时，在 `backend/.env` 中填写相同数据库口令，并使用 `MYSQL_HOST=localhost`、`ES_URL=http://localhost:9200`、`ES_USER=`、`DATA_DIR=data`。

若使用自行安装的 MySQL，先创建 UTF-8 数据库，再在该库内导入 `ragent_init.sql`。导入脚本含 `DROP TABLE`，只应对新建的演示库执行。

```bash
cd backend
python run.py
```

后端地址为 `http://127.0.0.1:8000`，交互式 API 文档为 `http://127.0.0.1:8000/docs`。可用 `python run.py --port 8001` 修改端口；前端开发代理也需同步调整。

### 前端

在另一个终端执行：

```bash
cd frontend
npm ci
npm run dev
```

默认访问 `http://localhost:5173`，`/api` 请求由 Vite 代理至本地后端的 8000 端口。

## 配置说明

详细字段见两个 `.env.example` 和 `backend/app/config.py`。

| 配置项 | 作用 |
| --- | --- |
| `LLM_PROVIDER` / `EMBED_PROVIDER` | 选择模型供应商；未设置时分别为 `deepseek` / `qwen` |
| `LLM_MODEL` / `EMBED_MODEL` / `EMBED_DIMS` | 覆盖供应商目录的模型或向量维度；留空使用目录默认值 |
| `LLM_BASE_URL` / `EMBED_BASE_URL` | 覆盖接口地址，用于网关或自建服务 |
| `RERANK_ENABLED` / `RERANK_PROVIDER` | 启用精排；当前支持 `qwen` 与 `siliconflow`，默认关闭 |
| `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_USER` / `MYSQL_PASSWORD` / `MYSQL_DB` | 应用数据库连接 |
| `ES_URL` / `ES_USER` / `ES_PASSWORD` | Elasticsearch 连接 |
| `CORS_ORIGINS` | 逗号分隔的允许来源；禁止通配符 `*` |
| `DATA_DIR` | 上传数据目录；相对路径以 `backend` 为基准 |
| `OVERALL_TIMEOUT` | 单次问答总超时，默认 120 秒 |

LLM 适配目录包含 `deepseek`、`qwen`、`openai`、`moonshot`、`zhipu`、`siliconflow`、`ollama`；Embedding 适配目录包含 `qwen`、`openai`、`siliconflow`、`ollama`。模型能力和默认值见 `backend/app/providers/registry.py`。

切换供应商时，应清理旧的模型和地址覆盖值，尤其是历史变量 `DEEPSEEK_BASE_URL` / `DASHSCOPE_BASE_URL`。切换 Embedding 模型后需重新向量化已有切片；维度变化时还需重建匹配维度的索引，不要直接对已有索引混用不同模型的向量。

## 测试与 CI

后端检查，在 `backend` 目录执行：

```bash
python -m ruff check .
python -m pytest -q
```

前端检查，在 `frontend` 目录执行：

```bash
npm run build
npm run test:coverage
```

普通单元测试隔离供应商密钥并模拟外部依赖，不需要真实 LLM / Embedding。真实 ES 隔离测试需要显式指定测试实例：

```powershell
# Windows PowerShell，在 backend 目录下执行
$env:RAGENT_TEST_ES_URL='http://localhost:9200'
python -m pytest -q
```

```bash
# macOS / Linux，在 backend 目录下执行
RAGENT_TEST_ES_URL=http://localhost:9200 python -m pytest -q
```

该测试仅创建并清理独立 UUID 临时索引；未指定环境变量时跳过真实 ES 用例。更多说明见 [检索、答案和引用回归](docs/testing/retrieval-correctness.md)。

[GitHub Actions 工作流](.github/workflows/ci.yml) 在推送 `main` / `master` 及 Pull Request 时运行：

- 后端：Ruff、pytest、真实 Elasticsearch 隔离回归，覆盖率至少 90%。
- 前端：类型检查、生产构建和 Vitest；语句/行覆盖率至少 90%，分支/函数至少 85%。
- 保存后端和前端覆盖率报告供下载。

**当前工作流提供 CI 验证，尚未配置镜像发布或自动部署（CD）。**

## 项目目录

```text
RAGent/
├── backend/
│   ├── app/agent/        # 问答编排、检索、提示词和 RRF
│   ├── app/providers/    # LLM / Embedding / Rerank 适配
│   ├── app/routers/      # 会话、知识库、数据源和日志 API
│   ├── app/services/     # 解析、切片、入库和图片管理
│   ├── scripts/          # 索引回填、重切与检索评测
│   └── tests/
├── frontend/src/         # 页面、组件、状态管理和 API 客户端
├── docs/                 # 国际化与回归验证说明
├── test_docs/            # 演示文档
├── elasticsearch/        # 可选 IK 插件镜像构建配置
├── .github/workflows/    # GitHub Actions CI
├── docker-compose.yml
└── ragent_init.sql       # 演示数据库建表和种子数据
```

## 当前使用边界

项目适合本地演示和开发验证。当前未实现用户认证及会话归属隔离，NL2SQL 路径仍使用应用数据库连接；正式共享部署前需要补齐访问控制和独立只读数据库权限。知识库范围过滤不等同于用户权限控制。

文档入库使用进程内后台任务，重启中断后的任务恢复和跨存储失败补偿尚不完整。扫描版 PDF 未配置 OCR。Nginx 默认配置也尚未对齐后端 20MB 文档上传上限，部署上传大文件时需调整请求体限制。

健康端点在依赖异常时可能仍返回 HTTP 200，请同时查看 JSON 中的 `status`、`mysql`、`elasticsearch` 和 `consistency`。不要仅凭页面能打开判断检索服务已就绪。
