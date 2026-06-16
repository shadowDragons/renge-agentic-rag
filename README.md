# Enterprise RAG Agent

一个面向企业内部知识管理场景的上传式 RAG 系统，支持本地文档入库、多知识库检索、引用式问答、人工审核工作流、任务中心、审计日志，以及基于 Langfuse 的观测、评测与 Prompt Management。

项目采用前后端分离架构：

- 后端：`FastAPI` + `SQLAlchemy` + `LangGraph`
- 检索：`LlamaIndex` + `Qdrant`
- 前端：`Vue 3` + `TypeScript` + `Element Plus`

## 功能特性

- 文档上传、解析、切块、向量入库
- 多知识库范围检索与引用片段回传
- SSE 流式问答
- LangGraph 澄清、审核挂起、审核恢复工作流
- 任务中心、审核台、审计日志、系统总览
- 本地开发可用的 `SQLite + Qdrant local mode`
- 基于 Langfuse 的：
  - chat turn trace
  - retrieval / rerank / generation span
  - usage / cost 记录
  - 人工审核 score
  - 离线评测
  - Prompt Management

## 技术栈

| 模块 | 技术 |
| --- | --- |
| 前端 | Vue 3、TypeScript、Vite、Element Plus、Pinia |
| 后端 | FastAPI、SQLAlchemy、Pydantic Settings、Uvicorn |
| 工作流 | LangGraph |
| RAG | LlamaIndex、Qdrant、dense retrieval、lexical rerank |
| 数据库 | SQLite、PostgreSQL |
| 文档解析 | pypdf、python-docx、antiword |
| 部署 | Docker、Docker Compose、Alembic |
| 观测与评测 | Langfuse |

## 项目结构

```text
Enterprise-RAG-Agent/
├── server/                  # FastAPI 后端服务
│   ├── app/                 # API、模型、服务、工作流、集成代码
│   ├── alembic/             # 数据库迁移
│   ├── scripts/             # 辅助脚本
│   └── tests/               # 后端测试
├── web/                     # Vue 3 前端应用
│   ├── src/
│   └── nginx/
├── docs/                    # 项目文档、面试/简历材料
├── kb-file/                 # 示例知识库与评测数据集
├── docker-compose.yml       # 单机 Demo 编排
└── README.md
```

## 快速开始

### 环境要求

- Python `3.11` 到 `3.13`
- Node.js `20+`
- npm `10+`
- 可选：Docker / Docker Compose
- 可选：`antiword`，仅本机直接解析 `.doc` 文件时需要；Docker 镜像内已自动安装

说明：

- 请不要直接使用 Python `3.14` 创建后端虚拟环境。当前依赖中的 `llama-index-vector-stores-qdrant` 仅支持 `Python < 3.14`。

### 1. 启动后端

```bash
cd server
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload
```

默认地址：

- API：`http://127.0.0.1:8000`
- OpenAPI：`http://127.0.0.1:8000/docs`

后端默认使用本地 `SQLite` 和嵌入式 `Qdrant`，适合本地开发体验，无需额外启动数据库或向量库。

### 2. 启动前端

```bash
cd web
npm install
cp .env.example .env
npm run dev
```

默认前端地址：

- `http://127.0.0.1:5175`

### 3. 登录系统

开发环境内置演示账号，仅用于本地体验：

| 角色 | 用户名 | 密码 | 说明 |
| --- | --- | --- | --- |
| 管理员 | `admin` | `admin123456` | 配置管理、运营处理、聊天 |
| 运营 | `operator` | `operator123456` | 运营处理、聊天 |
| 访客 | `viewer` | `viewer123456` | 只读聊天 |

登录后可以创建知识库、上传文档、配置助理并开始问答。

## 模型与 Embedding 配置

项目兼容 OpenAI 风格接口。默认 `.env.example` 中：

- Embedding 示例使用 SiliconFlow 的 `BAAI/bge-large-zh-v1.5`
- LLM 示例使用 OpenAI 的 `gpt-4o-mini`

常用配置项：

```env
# Embedding
EMBEDDING_PROVIDER=openai
OPENAI_EMBEDDING_BASE_URL=https://api.siliconflow.cn/v1
OPENAI_EMBEDDING_MODEL_NAME=BAAI/bge-large-zh-v1.5
OPENAI_EMBEDDING_DIMENSIONS=1024
OPENAI_EMBEDDING_API_KEY_ENV_VAR=SILICONFLOW_API_KEY
SILICONFLOW_API_KEY=your-siliconflow-key

# LLM
LLM_PROVIDER=openai
OPENAI_LLM_BASE_URL=https://api.openai.com/v1
OPENAI_LLM_MODEL_NAME=gpt-4o-mini
OPENAI_LLM_API_KEY=your-openai-key
```

如果你使用其他 OpenAI 兼容服务，通常只需要调整：

- `*_BASE_URL`
- `*_MODEL_NAME`
- API Key

## Langfuse

项目已接入 Langfuse，用于：

- 聊天 trace 与 workflow span 观测
- LLM generation 的 usage / cost 记录
- 人工审核结果与离线评测 score 回写
- Prompt Management 版本管理

### 开启 Langfuse Trace

先在 Langfuse Cloud 或 self-host 项目里创建项目并复制 API keys，然后配置：

```env
LANGFUSE_ENABLED=true
LANGFUSE_HOST=https://cloud.langfuse.com
# 如果你使用美国区 Cloud，可改成 https://us.cloud.langfuse.com
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_SAMPLE_RATE=1.0
LANGFUSE_CAPTURE_INPUT_OUTPUT=false
```

启用后，当前会记录：

- `enterprise-rag.chat_turn`
- `workflow.*`
- `rag.retrieval`
- `rag.rerank`
- `llm.answer_generation`
- usage / cost
- 脱敏后的 citation metadata
- `human_review_decision`

说明：

- `LANGFUSE_CAPTURE_INPUT_OUTPUT=false` 时，默认不记录完整问题、prompt、答案和引用原文，只记录结构化 metadata、score、usage、cost。
- 如需在 Langfuse Preview 中查看完整输入输出，可临时改成 `true` 后重启后端。

### 离线评测

系统页内置离线评测入口，当前支持：

- `hr_small`
- `support_small`
- `prd_small`

当前评测会产出并可回写到 Langfuse 的分数：

- `answer_relevance`
- `groundedness`
- `citation_quality`

接口：

- `POST /api/v1/system/evaluations/run`
- `GET /api/v1/system/evaluations/datasets`

### Prompt Management

项目已按“Langfuse provider + 本地 fallback”方式接入 Prompt Management。建议运行时按 label 读取，不要在代码里写死版本号。

配置项：

```env
LANGFUSE_PROMPT_MANAGEMENT_ENABLED=true
LANGFUSE_PROMPT_LABEL=production
LANGFUSE_PROMPT_CACHE_TTL_SECONDS=60
```

首次把本地 fallback prompt 注册到 Langfuse：

```bash
cd server
LANGFUSE_PROMPT_MANAGEMENT_ENABLED=true ./.venv/bin/python scripts/seed_langfuse_prompts.py
```

运行时可通过 trace 或系统页离线评测结果查看：

- `prompt_name`
- `prompt_version`
- `prompt_source`

其中：

- `prompt_source=langfuse`：已使用 Langfuse 托管 prompt
- `prompt_source=langfuse_fallback`：请求 Langfuse 失败后回退
- `prompt_source=local_fallback`：当前仍在使用本地 prompt

## Docker 部署

### 1. 单机 Demo

根目录提供了单机编排，适合个人演示或自用，后端使用本地 `SQLite + Qdrant local mode`：

```bash
docker compose up --build -d
```

默认地址：

- 前端：`http://127.0.0.1:8080`
- 后端 API：`http://127.0.0.1:8000`
- OpenAPI：`http://127.0.0.1:8000/docs`

常用环境变量：

```bash
export AUTH_SECRET_KEY='replace-with-a-random-secret'
export SILICONFLOW_API_KEY='your-siliconflow-key'
export OPENAI_LLM_API_KEY='your-openai-key'
export VITE_API_BASE_URL='http://localhost:8000/api/v1'
```

### 2. 后端生产依赖编排

`server/docker-compose.yml` 提供了 PostgreSQL + Qdrant + API 的后端编排：

```bash
cd server
docker compose up --build
```

该编排会启动：

- `postgres`
- `qdrant`
- `api`

生产环境请至少修改：

- `AUTH_SECRET_KEY`
- `DATABASE_URL`
- `WORKFLOW_CHECKPOINTER_POSTGRES_URL`
- `OPENAI_LLM_API_KEY` 或对应模型服务密钥
- `SILICONFLOW_API_KEY` 或对应 Embedding 服务密钥
- `CORS_ORIGINS`

## API 概览

后端默认 API 前缀为 `/api/v1`。

| 能力 | 路径 |
| --- | --- |
| 登录与当前用户 | `/auth/login`、`/auth/me` |
| 助理管理 | `/assistants` |
| 知识库管理 | `/knowledge-bases` |
| 文档上传与删除 | `/knowledge-bases/{id}/documents` |
| 会话管理 | `/sessions` |
| 聊天流式问答 | `/sessions/{session_id}/chat/stream` |
| 任务中心 | `/jobs` |
| 审核任务 | `/reviews` |
| 系统总览 | `/system/overview` |
| 健康检查 | `/health` |

完整接口请访问启动后的 OpenAPI 文档：

- `http://127.0.0.1:8000/docs`

## 文档上传说明

当前支持以下格式：

- 文本类：`txt`、`md`、`csv`、`json`、`yaml`、`yml`、`xml`、`html`
- PDF：`pdf`
- Word：`doc`、`docx`

说明：

- `.pdf` 使用 `pypdf` 提取文本，不包含 OCR；扫描件 PDF 需要额外接入 OCR。
- `.docx` 使用 `python-docx` 提取段落和表格文本。
- `.doc` 使用 `antiword` 提取文本；Docker 环境已内置，本机运行需自行安装。
- 上传后会创建异步处理任务，可在任务中心查看进度、失败原因和重试入口。

## 示例数据

- 示例知识库与评测数据集位于 [kb-file](./kb-file/)
- 评测数据集位于：
  - [kb-file/evaluation_datasets/hr_small_dataset.json](./kb-file/evaluation_datasets/hr_small_dataset.json)
  - [kb-file/evaluation_datasets/support_small_dataset.json](./kb-file/evaluation_datasets/support_small_dataset.json)
  - [kb-file/evaluation_datasets/prd_small_dataset.json](./kb-file/evaluation_datasets/prd_small_dataset.json)

## 文档

- [Langfuse 接入开发计划](./docs/Langfuse接入开发计划.md)
- [面试准备](./docs/面试准备.md)
- [简历](./docs/简历.md)

## 贡献指南

欢迎提交 Issue 和 Pull Request。建议在提交前运行：

```bash
cd server
source .venv/bin/activate
pytest

cd ../web
npm run build
```

如果改动涉及数据库结构，请同时补充 Alembic 迁移；如果改动涉及核心问答流程，请同步更新相关文档。

## License

开源前请根据你的发布计划补充许可证文件，例如 MIT、Apache-2.0 或其他许可证。
