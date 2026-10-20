# i18n 国际化方案（中 / 英）

RAGent 采用「UI 文案与业务输出分离」的双层国际化方案：

| 层 | 内容 | 机制 | 语言来源 |
|---|---|---|---|
| 前端静态文案 | 按钮、标题、占位符、aria-label、空态等 | `vue-i18n` + `src/i18n/locales/{zh-CN,en-US}.ts` | 用户选择（localStorage `ragent-locale` → 浏览器语言 → `zh-CN`） |
| 后端输出 | SSE 决策链 detail、API 错误消息 | `app/i18n.py` 的 `MESSAGES` 目录 + `ContextVar` + `Accept-Language` | 请求头 `Accept-Language`（由前端 `apiJson` / `ask()` 自动附加） |
| LLM 提示词 | Router/Planner/Grader/CRAG/Reflect/NL2SQL/Generate/Chat | `app/agent/prompts.py` 的 `PROMPTS` 双语 bundle | **提问语言**（`llm.detect_lang(question)`），与 UI 语言无关 |

> 关键约定：**答案语言跟随提问语言**。中文提问得到中文答案，英文提问得到英文答案——即使 UI 是另一种语言。原因：检索与生成的质量依赖问题语义，强行翻译提问会破坏检索命中。

## 语言协商流程

```
浏览器
  └─ locale store（localStorage / navigator.language）
       ├─ vue-i18n → 渲染静态文案
       └─ Accept-Language 头（apiJson / ask）
            └─ FastAPI LocaleMiddleware
                 └─ set_locale(resolve_locale(header))  ← ContextVar
                      ├─ 路由处理器 t() → HTTPException 消息
                      └─ run_ask(locale=...) → SSE detail 文案
```

- `LocaleMiddleware` 在请求进入时解析 `Accept-Language` 写入 ContextVar。
- `run_ask` 是异步生成器，函数体在**流式阶段**才执行，此时 ContextVar 可能已失效；因此 `chat.py` 在路由处理器内先 `current_locale()` 再显式传入 `run_ask(locale=...)`。
- HTTPException 的 `t()` 在路由处理器内执行，直接读 ContextVar 即可。

## 目录结构

```
frontend/src/i18n/
  index.ts                 # createI18n 实例
  locales/zh-CN.ts         # 中文目录（唯一中文文案来源）
  locales/en-US.ts         # 英文目录（key 必须与 zh 完全一致）
  locales/__tests__/parity.test.ts  # key 树一致性 / 非空门禁

frontend/src/stores/locale.ts       # 语言 store（持久化 + <html lang>）
frontend/src/components/layout/TopNavBar.vue  # 中 / EN 切换器

backend/app/i18n.py        # LocaleMiddleware / resolve_locale / t / MESSAGES
backend/app/agent/prompts.py  # PROMPTS 双语 bundle + 各 user builder
backend/app/agent/llm.py   # detect_lang（按 CJK 占比）

backend/tests/test_i18n.py              # 基建测试
backend/tests/test_i18n_orchestrator.py # SSE/API 文案测试
backend/tests/test_i18n_prompts.py      # 提示词测试
scripts/verify_i18n.py     # 端到端自检（前后端 key 一致性 + 双向渲染）
```

## 新增文案

### 前端
1. 在 `zh-CN.ts` 与 `en-US.ts` **同时**加同层级 key（命名空间式，如 `kb.upload.title`）。
2. 组件内 `const { t } = useI18n()`，模板/脚本用 `t('kb.upload.title')`。
3. `npm test` 会自动校验两语言 key 树一致。

### 后端（SSE / API）
1. 在 `app/i18n.py` 的 `MESSAGES` 加 `{"zh-CN": ..., "en-US": ...}`。
2. 调用处用 `t("key", locale, **params)`（locale 省略时读 ContextVar）。
3. `pytest tests/test_i18n_orchestrator.py` 会校验 `t("sse.*")` / `error.*` / `disclaimer.*` 的 key 都已入目录。

### LLM 提示词
1. 在 `prompts.py` 加 `*_ZH` / `*_EN` 两个常量并注册进 `PROMPTS`。
2. 若新增 user builder，签名带 `locale: str = "zh-CN"`，内部按 `locale` 分支。
3. `pytest tests/test_i18n_prompts.py` 会校验 bundle key 一致且英文无中文。

## 新增语言

1. 前端：复制 `zh-CN.ts` → `xx-XX.ts`，翻译值，保持 key 不变；在 `i18n/index.ts` 注册；`locale` store 的 `SUPPORTED` 增加该语言。
2. 后端：`i18n.SUPPORTED` 增加语言；`resolve_locale` 增加前缀分支；`MESSAGES` 每个 entry 增加该语言值；`PROMPTS` 增加 bundle。
3. 同步更新 `scripts/verify_i18n.py` 与 `detect_lang`。

## 验证

```bash
# 后端全量
cd backend && python -m pytest -q

# 前端全量（含 parity）
cd frontend && npm test

# 端到端自检（前后端 key 一致性 + 双向渲染抽样）
python scripts/verify_i18n.py
```

## 已知边界

- **示例问题内容保持中文**：`api/samples.ts` 的 `question`、Playground 的示例 `q` 是打中文知识库的真实查询，不随 UI 语言翻译；仅其展示标签随语言切换。
- **终端日志不翻译**：`startup_check.py`、`logger.*` 等运维诊断输出保持中文，仅对用户可见的 SSE/API/UI 文案做双语。
- **答案语言跟随提问**，见上方「关键约定」。
