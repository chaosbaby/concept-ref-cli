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

## CLI 交互标准 (The Gold Standards)

### 1. 核心输出模式 (Output Modes)
所有 Factory 生成的工具必须支持以下四种输出模式：
- **`show` (默认)**: 面向人类。支持 ANSI 颜色、加粗。对于诗词、长文等特殊数据源，应触发专用排版。
- **`plain`**: 面向管道工具（如 `awk`, `cut`）。仅输出空格分隔的数据值，无装饰。
- **`json` / `stream`**: 面向程序。单行 NDJSON 格式，兼容 `jq`。

### 2. 补全管理 (Completion)
必须提供 `completion` 子命令组：
- `show`: 打印对应 Shell 的补全脚本。
- `install`: 自动识别 Shell 环境并注入 `eval` 语句到用户配置（需确认）。

### 3. 特性自省 (Features)
`features` 命令应支持状态过滤：
- `--status ok`: 显示已实现的工业级特性。
- `--status miss`: 显示尚未实现的强制特性（Roadmap）。
- `--status opt`: 显示可选特性。

### 4. 管道流协议 (Pipe-Stream)
`search` 指令必须支持 `stdin` 作为输入源（通常使用 `-` 参数或 `--stdin` 标志）。

### 5. JSON 更新协议 (JSON Update Protocol)
在维护 `features-manifest.json` 或其他持久化 JSON 数据时，必须遵守：
1. **禁止全量覆盖**: 更新前必须执行 `read_file`。
2. **原子合并**: 使用字典更新/列表映射逻辑，保留未修改的原始字段（如 `trigger`, `integration`）。
3. **数据校验**: 写回前确保关键字段（id, rank 等）符合 Schema 要求。
4. **规范化排序**: 存储前强制使用 `jq 'sort_by(.id)'` 排序，确保 Git 记录的稳定性。
5. **变更审计**: 操作完成后需简报 diff 差异，禁止静默删除字段。
