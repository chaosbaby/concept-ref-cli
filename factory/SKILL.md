---
name: concept-cli-factory
description: 交互式中文文化数据 CLI 工厂。支持特性驱动的子命令架构与深度参数化过滤。
---

# Concept CLI Factory (Advanced Sub-command Edition)

## 核心原则 (Core Principles)

1. **子命令隔离 (Functional Sub-commanding)**:
   - 不同性质的数据源必须拥有独立的子命令（如 `dict`, `ids`, `cc`）。
   - 每个子命令定义其专属的参数集（如词典支持 `rank/tag` 过滤，拆解支持 `depth` 过滤）。
2. **特性矩阵 2.0 (Deep Manifest)**:
   - `features` 命令必须展示：支持的特性、各特性的配置项、以及当前的默认参数。
3. **参数过滤矩阵 (Filter Matrix)**:
   - 必须支持区间过滤（`min-max`）、集合过滤（`in/not in`）和正则过滤。
4. **配置持久化 (Configuration)**:
   - 必须提供 `config` 指令，支持设置默认输出格式、默认搜索范围等。

## 技术协议 (The Standards)
- **Sub-commands**: `tool <source_id> [action]`
- **Global Features**: `tool sql`, `tool features`, `tool config`.
- **Filtering**: 使用 SQL 底层进行 `range/tag` 过滤，严禁在 Python 层进行大数据量循环过滤。
