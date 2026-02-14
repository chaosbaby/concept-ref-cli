# Concept Ref CLI (Master Edition)

本项目是一个高性能的中文文化数据工具集，基于 SQLite FTS5 全文检索与 Rich 终端渲染引擎构建。

## 核心工具

### 1. `xh` (新华字典大师版)
集成字典、词典、成语、歇后语查询。

*   **高性能搜索**: 升级 FTS5 引擎，支持字级 Tokenization 的极速子串匹配。
*   **精美渲染**: 集成 `rich` 渲染引擎，提供自动适配终端颜色的精美面板排版。
*   **统一协议**: 所有命令支持 `-o/--output (show, json, plain)` 及 `--stream` 流处理。
*   **灵感捡拾**: `xh pick` 随机抽取高质量词条。
*   **运维指令**: `xh schema` 自省表结构，`xh doctor` 诊断数据库健康度。

### 2. `lexicon` (现代汉语词库 - 模块化重构版)
提供词频、字形构件（IDS）及同义词林等专业数据。

*   **原子化模块**: 子命令隔离 (`lexicon dict`, `lexicon ids`)。
*   **多维过滤**: 支持按词频 (`--rank`)、词长 (`--len`) 进行区间过滤。
*   **智能补全**: 内置毫秒级补全引擎，支持 Shell 自动补全。
*   **持久化配置**: 支持 `config set/get` 锁定默认输出格式与限制。

### 3. `cpt` (中华诗歌 - 高性能修正版)
支持全唐诗、宋词等海量数据的检索与渲染。

*   **统一输出**: 支持 `json` 和 `ndjson` 格式，便于下游工具链集成。
*   **智能排版**: 支持格律诗的垂直/水平排版切换。

## 通用特性 (Standard Protocols)

- **输出模式 (-o)**: 
  - `show`: Rich 面板精装版（默认）。
  - `json`: 结构化 JSON 单行模式。
  - `plain`: 适合 grep/sed 的纯文本模式。
- **流处理**: 全面支持 `sys.stdin` 管道输入（`-` 或 `--stream`）。
- **配置中心**: 使用 `config` 命令管理个性化默认值。

## 开发与扩展

### Concept CLI Factory
本项目内置了一个 `factory` 目录，通过 `concept-cli-factory` 技能引导开发者将文化数据转化为工业级 CLI。

*   **架构标准**: 强制执行特性驱动（Feature-Driven）的清单式管理。
*   **原子开发**: 基于 Conductor Tracks 的渐进式开发流程。

## 安装与运行

```bash
pip install -e .
xh init  # 初始化字典库
```

## 数据来源
- [chinese-poetry](https://github.com/chinese-poetry/chinese-poetry)
- [chinese-xinhua](https://github.com/pwxcoo/chinese-xinhua)
