# 检索、答案和引用回归

## 行为约定

- 指定 `kb_ids` 时，向量候选在 `knn.filter` 内限制范围；不传范围时仍检索全部知识库。
- 反思重生成通过 `generate` 事件的 `replace: true` 清空旧正文，再发送新轮次增量。
- `citation` 事件携带最终 `answer`，用于同步非法引用清理和自检警示；它与落库正文一致。
- 新引用携带原始 `ref_id`，以及文档的 `doc_id`、`kb_id` 和 `chunk_uid`。正文 `[3]` 对应 `ref_id=3`，不取引用数组的第三项。
- 引用按文档 ID 和切片 UID 定位。源文档删除或重新入库导致 UID 失效时返回 404，不跳转到同名文档或新切片。
- 历史引用没有编号时，前端按正文中编号首次出现的顺序恢复映射；没有文档 ID 时仅允许唯一文件名回退。同名文档返回 409，提示重新提问。文件名按最后一个点去扩展名。
- 快速切换引用后，旧请求的成功、失败和完成回调均不能更新当前抽屉。

新增协议字段存储在现有 JSON 字段内，不需要表结构迁移。前后端应一起更新。历史错误正文不会被自动重写。

## 本地验证

后端完整检查（在 `backend` 下）：

```powershell
python -m ruff check .
python -m pytest -q
```

真实 Elasticsearch 隔离测试需要一个可访问、无鉴权的测试实例：

```powershell
$env:RAGENT_TEST_ES_URL='http://localhost:9200'
python -m pytest tests/test_es_isolation_integration.py -q --no-cov
```

测试仅创建 UUID 命名的 `ragent-isolation-test-*` 临时索引，并在结束时删除该索引；不读取或修改业务索引。数据特意让其他库的向量更相似，验证指定单库、多库、空结果和未指定范围的行为，并用旧查询作为失败对照。未配置环境变量时跳过这组测试；CI 后端作业启动独立 ES 服务并执行它们。

前端检查（在 `frontend` 下）：

```powershell
npm run test:coverage
npm run build
```

核心回归覆盖反思答案替换、正文与落库一致、乱序/稀疏引用编号、历史引用、同名文档、失效切片以及抽屉异步响应竞争。测试不调用真实 LLM/Embedding 供应商。
