# Product Definition & Engineering Standards

## 1. Project Goal
Build high-performance, Unix-style CLI tools for Chinese cultural data.

## 2. Engineering Standards (High Priority)

### 2.1 大数据处理规范 (Large Data Protocol - Token Economy)
在处理大规模数据文件时，必须严格遵守以下优先级（按经济性/Token消耗从低到高排序）：

1.  **元数据优先 (Metadata First)**: 
    - 任何操作前先执行 `ls -lh`。
    - 若文件 > 1MB，视为“危险区域”，严禁直接读取或 `cat`。
2.  **结构化采样 (Structural Probing)**: 
    - 使用 `head -c 1024` 查看文件头确认编码。
    - 对于单行 JSON，使用 `jq -c 'keys'` 或 `jq '.[0]'` 提取结构。
3.  **精确提取 (Selective Extraction)**: 
    - 使用 `rg -o` 仅提取匹配项。
    - 配合 `--max-columns 500` 限制单行输出，防止超长行导致 Token 爆炸。
4.  **流式统计 (Streamed Stats)**: 
    - 在确认非单行大文件后，方可使用 `wc -l` 统计行数。
5.  **按需分页 (Pagination)**: 
    - 必须使用 `read_file` 的 `offset` 和 `limit` 参数。
    - 默认分页建议：`limit: 50`。

### 2.2 CLI 交互规范
- 遵循 Linux 工具哲学：组合性强、输出可预测（NDJSON/Plain）。
- 搜索结果默认限制 20 条，支持 `--limit`。
