---
name: concept-cli-factory
description: 交互式中文文化数据 CLI 工厂。通过“感知-诊断-构建-增强”四个阶段，引导用户将原始数据转化为工业级的流处理与查询工具。支持特性驱动的子命令架构与深度参数化过滤。
---

# Concept CLI Factory (Master Edition)

本技能通过渐进式交互与严格的架构标准，引导协作构建高性能 CLI 工具。

## 1. 交互原则 (Interaction Protocols)

1.  **锁定自动提交 (Strict Commit Locking)**：
    *   **禁止**在任务完成后自动执行 `git commit`。
    *   只有当用户在指令中明确包含“执行后并提交”或“验收并提交”等强调语时，方可自动提交。
2.  **强制轻量测试 (Mandatory Testing)**：
    *   在每个功能开发流程或 Track 节点完成后，**强制**执行轻量级测试（如运行命令验证输出、检查配置保存情况）。
    *   测试失败必须立即修复，严禁将未验证的代码交付验收。
3.  **确认后执行 (Confirm-Before-Action)**：
    *   在推荐新特性或规划复杂逻辑后，必须列出理由并等待用户明确确认。
4.  **反馈回路 (Feedback Loop)**：
    *   每一个工具调用（如 `write_file`, `init`）后，必须向用户简报结果。

## 2. 核心流程 (SOP)

### Phase 0: 诊断与感知 (Sensing & Diagnosis)
1. **目录嗅探**: 扫描项目结构，建立命令与数据目录（如 `sources/lexicon`）的映射。
2. **数据探测 (Token Economy)**: 
    *   **Size**: 首先执行 `ls -lh` 评估规模。
    *   **Format**: 使用 `head -c 1024` 或 `file` 判定。如果是单行 JSON，使用 `jq -c 'keys'`。
    *   **Sample**: 对于大文件，严禁全量读取，必须使用 `rg -o` 提取特征或分页 `read_file`。
3. **输出报告**: 包含数据规模预估、建议 Schema、发现的额外功能及潜在问题。
4. **决策点**: 询问用户是否同意诊断结果，并选择首选功能。

### Phase 1: 基础构建 (Base Implementation)
- `init`: 高性能 SQLite 导入（支持 `batch-loader`）。
- `search`: FTS5 全文搜索 + 精确匹配 + 权重排序。
- `stream`: 支持管道输入（stdin）和输出（NDJSON/Plain）。
- `completion`: 自动安装 Shell 补全。

### Phase 2: 渐进式增强 (Interactive Expansion)
- **子命令隔离**: 不同数据源拥有独立命令空间。
- **特性矩阵**: 动态读取 `features-manifest.json` 展示特性状态。
- **智能排版**: 根据数据内容自动触发垂直排版。
- **随机灵感**: 提供高质量随机推荐。

### Phase 3: 交付与体检 (Delivery & Doctor)
- `doctor`: 检查数据库状态、索引健康度。
- `schema`: 自省底层字段定义。
- `readme`: 自动生成使用说明。

## 3. 架构标准 (The Standards)

1. **特性驱动 (Feature-Driven)**: 
   - `features` 命令必须实时反映 `features-manifest.json` 中的状态。
   - **权重排序 (Ranked Display)**: 输出必须根据 `rank` 字段从高到低排列，优先展示核心与高价值特性。
   - 状态词：`implemented` (✅ OK), `recommended`/`optional` (⚪ OPT), `na` (🚫 N/A - 抵触/不兼容)。
   - `implemented` 状态应与代码逻辑严格对齐。
   - **高亮展示 (Search Highlighting)**: 在 `-o show` 模式下，输出内容必须对搜索关键词（Query）进行视觉高亮处理，并配合颜色排版。而在 `-o plain` 模式下，严禁包含任何 ANSI 颜色或排版装饰，仅输出纯文本。
2. **多维过滤 (Filter Matrix)**:
   - 必须支持区间过滤（`min-max`）、集合过滤（`in/not in`）。
   - **强制补全 (Tag Completion)**: 对于基数（Unique Values）在 100 以下的 Tag 类字段（如朝代、类型、标签），必须实现动态 Shell 补全，以提升交互效率。
3. **配置持久化 (Configuration)**:
   - 提供 `config` 指令，支持持久化默认输出格式、搜索限制等。
4. **技术指标**:
     - **DB**: `~/.<tool_id>.db`。
     - **Format**: 必须支持四大输出模式：
       1. `show`: 高亮排版精装版。
       2. `plain`: 无颜色纯文本原味版。
       3. `json`: 标准 JSON 数组格式 `[...]`。
       4. `ndjson`: 换行符分隔的 JSON 对象流格式，每行一个对象。
     - **Stream**: `sys.stdin` 必须能处理 `search` 查询流。
5. **JSON 数据维护协议 (JSON Update Protocol)**:
   - **禁止全量重写 (No Blind Overwrite)**: 更新时必须先读取当前内容，在内存中原子合并后再写回，防止字段丢失。
   - **Schema 校验 (Schema Guard)**: 写回前强制执行关键字段（id, rank 等）的完整性校验。
   - **规范化排序 (Canonical Sorting)**: 强制使用 `jq 'sort_by(.id)'` 对存储文件进行排序，以确保 Git Diff 的最小化。
   - **变更审计 (Audit)**: 完成后必须执行 diff 检查并简报差异。
   ## 4. 目录真理源 (Directory Mapping)
- **Source of Truth**: `skills/concept-cli-factory/`
- **Mapping**: `.gemini/skills/concept-cli-factory` 为软连接。
- **Metadata**: 特性状态记录在 `references/features-manifest.json`。
