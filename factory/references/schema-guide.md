# 中文文化数据 Schema 设计指南

为不同的数据集选择合适的索引和存储策略。

## 1. 字典/词典类 (Dictionary/Lexicon)
**核心需求**: 快速定位字词，支持拼音、笔画、部首。
- **Primary Key**: 字/词本身。
- **索引**: 拼音字段（B-Tree），部首（B-Tree）。
- **优化**: 对于解释（Explanation）字段，如果较长，考虑启用 FTS5。

## 2. 诗词/古文类 (Poetry/Classics)
**核心需求**: 全文检索，按作者搜索，按朝代过滤。
- **存储**: 使用 `FTS5` 虚拟表存储正文。
- **字段**: `title`, `author`, `dynasty`, `content` (FTS), `tags`.
- **查询**: 使用 `MATCH` 操作符进行模糊搜索。

## 3. 关联类 (e.g. 歇后语/对联)
**核心需求**: 搜索前半部分或后半部分。
- **索引**: 对 `riddle` 和 `answer` 分别建立索引。

## 4. 大规模数据导入优化
- **事务**: 始终使用 `BEGIN` 和 `COMMIT`。
- **Batch**: 使用 `cursor.executemany` 且 batch size 建议在 1000-5000。
- **Pragmas**:
    ```sql
    PRAGMA synchronous = OFF;
    PRAGMA journal_mode = MEMORY;
    ```
