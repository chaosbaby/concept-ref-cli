# Concept Ref CLI

本项目是一个高性能的中华文化数据查询工具集，目前包含诗词 (`cpt`) 和新华字典 (`xh`) 两个核心工具。

## 核心工具

### 1. `cpt` (中华诗歌 CLI)
支持全唐诗、全宋诗、宋词、元曲等海量数据的检索。

*   **数据初始化**: `cpt init` (智能去重，支持内容指纹校验)
*   **搜索**: `cpt search "李白"`
*   **朝代过滤**: `cpt search "月" --dynasty 唐`
*   **随机荐诗**: `cpt random-one`
*   **作者查询**: `cpt author "杜甫"`

### 2. `xh` (新华字典 CLI)
提供字典、词典、成语、歇后语的高效查询。

*   **初始化**: `xh init`
*   **查找汉字**: `xh word "禅"`
*   **查找成语**: `xh idiom "心猿意马"`
*   **查找词语**: `xh ci "代码"`
*   **全局搜索**: `xh search "文化"`

## 开发与扩展

### Concept CLI Factory
本项目内置了一个 `factory` 目录，已注册为 Gemini CLI 的 Agent Skill。它可以引导开发者快速将原始文化 JSON/CSV 数据转化为工业级的 CLI 工具。

*   **激活 Skill**: `activate_skill concept-cli-factory`
*   **核心特性**: 高性能导入模板、内容指纹去重 SOP、FTS5 全文检索。

## 安装与运行

```bash
pip install -e .
```

## 数据来源
- [chinese-poetry](https://github.com/chinese-poetry/chinese-poetry)
- [chinese-xinhua](https://github.com/pwxcoo/chinese-xinhua)
