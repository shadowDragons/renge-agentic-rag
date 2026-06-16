# Langfuse 接入开发计划

本文档记录 Enterprise-RAG-Agent 引入 Langfuse 的分阶段计划。目标不是“接上观测工具”本身，而是把 RAG 系统逐步建设成具备可观测、可评测、可实验对比和可持续优化能力的企业级知识库问答系统。

## 总体策略

先接观测，再接评测，最后接 Prompt 与实验管理。

不建议第一阶段就把所有 prompt 迁移到 Langfuse。Prompt 迁移会同时影响运行链路、配置链路和质量评估，应该等 trace、score、dataset 和实验对比跑通后再做。

当前推荐顺序：

1. 配置和 Langfuse wrapper
2. chat turn trace
3. retrieval / rerank / generation span
4. LLM generation 记录
5. 人工审核结果写入 score
6. Dataset + 离线评测
7. 实验对比
8. Prompt Management

## 当前完成状态

截至当前版本，已完成：

- Langfuse Cloud POC 配置接入
- `LANGFUSE_*` 配置项与 Docker Compose 环境变量
- `app/integrations/langfuse_tracing.py` 旁路封装
- 每轮聊天 trace：`enterprise-rag.chat_turn`
- 检索 span：`rag.retrieval`
- 回答 generation：`llm.answer_generation`
- 人工审核 score：`human_review_decision`
- 默认脱敏：不记录完整 prompt、answer、citation 原文
- Langfuse 异常不影响聊天主链路
- UUID trace id 自动转换为 Langfuse v3 需要的 32 位 hex
- `workflow.*` 节点 span 已串联到 chat turn trace
- 生产类环境在未显式配置 `LANGFUSE_SAMPLE_RATE` 时默认采样 `0.2`
- generation 已记录 token usage
- 已为当前实际使用模型补本地静态定价表，并写入 Langfuse `cost_details`
- `rag.rerank` span 已记录候选前后 top chunks 与分数变化
- 离线评测支持独立模型超时配置 `EVALUATION_LLM_REQUEST_TIMEOUT_SECONDS`，默认 `180` 秒，不影响线上聊天默认 `60` 秒
- 已扩展 3 组命名评测数据集：`hr_small` / `support_small` / `prd_small`
- 已新增 `EvaluationDatasetRegistry`，评测数据集改为通过 registry 管理
- 已新增 Langfuse Prompt Management 适配层，业务侧通过 provider 获取 prompt
- 回答生成 prompt 已接入 Langfuse Prompt Management，并保留本地 fallback
- 澄清 / 无命中 / review 提示模板已接入 Langfuse Prompt Management，并保留本地 fallback
- 已提供 prompt seed 脚本：`server/scripts/seed_langfuse_prompts.py`
- 已在 Langfuse Cloud 中完成以下 prompt 的 seed，当前为 `v1`：
  - `enterprise_rag_answer_generation`
  - `enterprise_rag_no_retrieval_hits`
  - `enterprise_rag_clarification_confirm_switch`
  - `enterprise_rag_clarification_new_topic_question`
  - `enterprise_rag_clarification_continue_current_topic`
  - `enterprise_rag_review_required`
  - `enterprise_rag_review_rejected`
- 当前本地运行环境已启用：
  - `LANGFUSE_PROMPT_MANAGEMENT_ENABLED=true`
  - `LANGFUSE_PROMPT_LABEL=production`
- 已验证当前 Prompt provider 可从 Langfuse 正常读取远端 prompt，而不是 fallback：
  - `prompt_source=langfuse`
  - `prompt_version=1`
- 系统页离线评测结果已支持显示：
  - `prompt_name`
  - `prompt_version`
  - `prompt_source`

尚未完成：

- Self-host 部署
- 完整自动评测器（当前只有启发式初版）
- Dataset 和离线实验平台化
- Prompt 实验对比与版本治理页面

已补最小 Phase 4 基础：

- `app/services/evaluation.py` 初版
- 本地 HR 小样本 Dataset：`kb-file/evaluation_datasets/hr_small_dataset.json`
- 本地客服 / 产品研发小样本 Dataset：
  - `kb-file/evaluation_datasets/support_small_dataset.json`
  - `kb-file/evaluation_datasets/prd_small_dataset.json`
- 支持 `answer_relevance` / `groundedness` / `citation_quality` 三类启发式 score
- 支持把上述 score 回写 Langfuse trace

## Prompt Management 当前用法

当前项目的 Prompt Management 已按“旁路 provider + 本地 fallback”方式接入：

- 开关：
  - `LANGFUSE_PROMPT_MANAGEMENT_ENABLED`
  - `LANGFUSE_PROMPT_LABEL`
  - `LANGFUSE_PROMPT_CACHE_TTL_SECONDS`
- 适配层：
  - `server/app/integrations/langfuse_prompt_management.py`
- 当前已接入的 prompt：
  - 回答生成 prompt
  - 澄清提示 prompt
  - 无命中提示 prompt
  - review required / rejected 提示 prompt

首次把本地 fallback prompt 注册到 Langfuse 可执行：

```bash
cd server
LANGFUSE_PROMPT_MANAGEMENT_ENABLED=true ./.venv/bin/python scripts/seed_langfuse_prompts.py
```

建议流程：

1. 先执行 seed，把本地默认 prompt 推到 Langfuse。
2. 在 Langfuse UI 中为 prompt 打上 `production` 或你的环境 label。
3. 打开 `LANGFUSE_PROMPT_MANAGEMENT_ENABLED=true` 后重启后端。
4. 再通过 trace 中的 `prompt_name` / `prompt_version` / `prompt_source` 验证是否已走远端 prompt。

当前系统页的离线评测结果也会显示每条样本使用的 `prompt_name` / `prompt_version` / `prompt_source`，便于做 prompt 对比和回归检查。

当前推荐的运行方式：

- 开发/验证：
  - `LANGFUSE_PROMPT_LABEL=production`
  - `LANGFUSE_PROMPT_CACHE_TTL_SECONDS=60`
- 正式多环境管理：
  - 测试环境使用 `staging`
  - 生产环境使用 `production`
  - 实验场景使用 `exp-*`

当前在 Langfuse UI 里应可直接看到：

- **Prompts**
  - 各 prompt 的 `Version=1`
  - `Labels` 至少包含 `production` / `latest`
- **Trace / Generation metadata**
  - `prompt_name`
  - `prompt_version`
  - `prompt_source`

其中：

- `prompt_source=langfuse`：当前已使用远端托管 prompt
- `prompt_source=langfuse_fallback`：请求 Langfuse 失败后回退
- `prompt_source=local_fallback`：Prompt Management 未启用或未生效

## Phase 0：部署与安全基线

目标：企业环境可控接入。

### 任务

- 优先支持 Langfuse self-host，Cloud 仅用于 POC。
- 在 `.env` / Docker 配置中增加：
  - `LANGFUSE_ENABLED`
  - `LANGFUSE_HOST`
  - `LANGFUSE_PUBLIC_KEY`
  - `LANGFUSE_SECRET_KEY`
  - `LANGFUSE_SAMPLE_RATE`
  - `LANGFUSE_CAPTURE_INPUT_OUTPUT`
  - `LANGFUSE_CITATION_CONTENT_LIMIT`
- 明确敏感数据策略：
  - 默认不记录完整文档原文。
  - citation content 默认只记录 hash 和结构化 metadata。
  - 用户问题、prompt、模型回答由 `LANGFUSE_CAPTURE_INPUT_OUTPUT` 控制。
- 生产环境建议采样 10%-30%，不要默认全量采集。
- 当前实现：若 `APP_ENV in {staging, prod, production}` 且未显式设置 `LANGFUSE_SAMPLE_RATE`，默认按 `0.2` 采样。

### 涉及文件

- `server/app/core/config.py`
- `server/pyproject.toml`
- `docker-compose.yml`
- `.env.example`
- `server/.env.example`

### 验收标准

- 本地和 Docker 环境都能开关 Langfuse。
- 关闭 Langfuse 时业务零影响。
- Langfuse 初始化、网络、API 异常不会导致聊天失败。
- Cloud POC 能看到 connectivity test trace。

## Phase 1：基础 Trace 接入

目标：每一轮聊天在 Langfuse 中形成完整 trace。

### 任务

- 新增 `app/integrations/langfuse_tracing.py`，封装 Langfuse SDK。
- 每次 chat turn 创建 trace，记录：
  - `session_id`
  - `workflow_thread_id`
  - `assistant_id`
  - `assistant_name`
  - `selected_kb_ids`
  - `top_k`
  - `fallback_reason`
- 在 LangGraph 调用外层埋 trace。
- 把现有 `workflow_trace` 同步到 Langfuse metadata。
- 保持业务审计日志和 Langfuse trace 并存，不互相替代。

### 涉及文件

- `server/app/integrations/langfuse_tracing.py`
- `server/app/services/chat_rag.py`
- `server/app/api/routes/chat.py`

### 验收标准

- Langfuse 能看到每轮用户问题对应的一条 trace。
- trace 能关联到本系统 session 和 assistant。
- 异常请求也能记录 error metadata。
- SSE 流式响应不受 Langfuse 上下文影响。

## Phase 2：RAG 链路细粒度 Span

目标：看清楚慢在哪里、差在哪里。

### 任务

增加以下 span：

- `resolve_context`
  - 会话历史数量
  - resolved question
  - current goal
  - intent drift score
- `select_knowledge_base`
  - 请求知识库
  - 实际选中知识库
- `rag.retrieval`
  - query
  - top_k
  - per_kb_top_k
  - overfetch factor
  - retrieved count
  - dense weight
  - lexical weight
- `rerank`
  - rerank 前后 top chunks
  - vector_score
  - lexical_score
  - final score
- `review_gate`
  - 是否命中人工审核
  - 命中规则
- `compose_answer`
  - 使用模型
  - citation_count
  - fallback_reason

### 涉及文件

- `server/app/workflows/chat_graph_execution.py`
- `server/app/workflows/chat_graph_clarification.py`
- `server/app/services/retrieval.py`
- `server/app/services/answer_generation.py`

### 验收标准

- 一次问答能看到 retrieval、rerank、generation 分段耗时。
- 能按 knowledge base、assistant、model 过滤 trace。
- 能定位“检索没命中”和“生成答坏了”是哪一段的问题。

## Phase 3：LLM Generation 观测

目标：把模型调用变成 Langfuse generation，记录模型调用输入、输出、错误、耗时和后续 token/cost。

当前项目在 `chat_model_provider.py` 中手写 OpenAI-compatible HTTP 调用，因此采用手工 generation 埋点，不依赖自动回调。

### 任务

- 非流式 `invoke` 记录：
  - model
  - messages
  - temperature
  - response
  - latency
  - error
- 流式 `stream` 记录：
  - 开始时创建 generation
  - 收集 delta
  - 结束时 flush 完整 output
  - 中断时记录 partial output / error
- 对输入输出增加脱敏和截断工具。
- 后续解析模型返回的 `usage` 字段，补充 token 和 cost。

### 涉及文件

- `server/app/services/answer_generation.py`
- `server/app/integrations/chat_model_provider.py`
- `server/app/integrations/langfuse_tracing.py`

### 验收标准

- Langfuse generation 里能看到模型、prompt、answer、耗时。
- 流式回答正常完成时能记录完整输出。
- 流式中断不影响 SSE 正常行为。
- token usage 和 cost 能进入 Langfuse generation。

## Phase 4：评测闭环

目标：从“能看 trace”升级到“能量化质量”。

### 指标

先做三类 score：

- `answer_relevance`：回答是否回应用户问题。
- `groundedness`：回答是否被引用片段支持。
- `citation_quality`：检索片段是否足够回答问题。

人工审核结果作为线上质量信号：

- approved：`human_review_decision = 1.0`
- rejected：`human_review_decision = 0.0`
- reviewer note：写入 score comment

### 任务

- 新增 `app/services/evaluation.py`。
- 从已完成 trace 中抽样生成评测任务。
- 支持 LLM-as-a-Judge rubric。
- 支持人工审核结果回写 Langfuse score。
- 建立小规模离线 Dataset：
  - HR 10-30 条
  - 客服 SOP 10-30 条
  - 产品研发 10-30 条

### 涉及文件

- `server/app/services/evaluation.py`
- `server/app/services/review_tasks.py`
- `server/app/services/audit_logs.py`
- `kb-file/`

### 验收标准

- 每个 Dataset run 能比较不同模型、prompt、top_k。
- 每条线上回答可以有人工或自动评分。
- 能找出低分样本并回灌到测试集。

## Phase 5：实验管理

目标：让检索和 prompt 优化有数据依据。

### 首批实验

- `top_k=4` vs `top_k=8`
- `retrieval_overfetch_factor=3` vs `5`
- `dense_weight=0.65` vs `0.5`
- 当前 prompt vs 更严格引用 prompt
- 当前 dense + lexical rerank vs 后续 hybrid retrieval

### 验收标准

- 每次实验有固定 Dataset。
- 对比指标包括：
  - answer relevance
  - groundedness
  - citation quality
  - latency
  - token cost
  - review hit rate
- 只有实验结果更优，才合并参数或 prompt 变更。

## Phase 6：Prompt Management

目标：把 prompt 从代码常量逐步迁到可版本化管理。

该阶段建议最后做，不要在观测和评测闭环稳定前执行。

### 迁移范围

- 回答生成 prompt
- 澄清 prompt
- 无命中兜底回答模板可以暂时保留在代码里

### 涉及文件

- `server/app/services/answer_generation.py`
- `server/app/workflows/chat_graph_clarification.py`

### 验收标准

- prompt 有版本号。
- trace 能记录使用的 prompt version。
- prompt 回滚不需要重新发版，或至少支持配置切换。

## 最小可交付版本

第一阶段展示版本建议包含：

- Cloud POC 或 self-host 配置
- 每轮聊天 trace
- retrieval span
- generation span
- review result score
- 一个 30 条 Dataset 的离线评测

这个版本已经可以体现企业级 RAG 的可观测与评测闭环，同时不会把项目改得太重。
