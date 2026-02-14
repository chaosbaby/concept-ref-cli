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
2. **数据取样**: 读取 JSON/CSV 的前几行，分析字段结构。
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
   - `implemented` 状态应与代码逻辑严格对齐。
2. **多维过滤 (Filter Matrix)**:
   - 必须支持区间过滤（`min-max`）、集合过滤（`in/not in`）。
3. **配置持久化 (Configuration)**:
   - 提供 `config` 指令，支持持久化默认输出格式、搜索限制等。
4. **技术指标**:
   - **DB**: `~/.<tool_id>.db`。
   - **Format**: 支持 `--json` (单行) 和 `--plain` (彩色)。
   - **Stream**: `sys.stdin` 必须能处理 `search` 查询流。

## 4. 目录真理源 (Directory Mapping)
- **Source of Truth**: `skills/concept-cli-factory/`
- **Mapping**: `.gemini/skills/concept-cli-factory` 为软连接。
- **Metadata**: 特性状态记录在 `references/features-manifest.json`。
