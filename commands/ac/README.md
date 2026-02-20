# ac - AI-Chat CLI

`ac` 是一个命令行工具，用于搜索和管理您的 AI 对话历史记录。它通过将对话日志同步到本地 SQLite 数据库，并提供强大的全文搜索（FTS5）、灵活的输出格式以及配置管理功能。

## 安装

首先，确保您已经在项目根目录下安装了 CLI 工具：

```bash
pip install -e .
```

## 功能与用法

### `ac sync` - 同步对话日志

将 `sources/ai-chat/conversations/` 目录下的 JSON 对话日志同步到本地 SQLite 数据库。支持增量同步。

```bash
ac sync [--data-dir <path>]
```

-   `--data-dir`: 对话日志所在的目录，默认为 `sources/ai-chat/conversations`。

**示例**:
```bash
ac sync
```

### `ac search` - 搜索对话历史

使用全文搜索功能，支持多种输出格式、Unix 管道流、Markdown 增强排版和结果限制。

```bash
ac search <query> [-o <output_mode>] [--limit <number>] [--stdin]
```

-   `<query>`: 搜索关键词。如果为 `-`，则从 stdin 读取。
-   `--stdin`: 从 stdin 读取搜索关键词。
-   `-o, --output`: 输出模式，可选值：`show` (默认，带高亮和排版), `plain` (纯文本), `json` (JSON 数组), `ndjson` (换行符分隔的 JSON 对象)。
-   `--limit`: 限制返回结果的数量，默认为 10 (可通过 `config` 配置)。

**示例**:
```bash
ac search "NeoVim"
ac search "AI 伦理" -o json
# Unix 管道流支持
echo "Gemini" | ac search -
ac search --stdin < query_file.txt
```

### `ac doctor` - 数据库健康诊断

检查数据库的健康状况、大小以及会话和消息的数量。

```bash
ac doctor
```

**示例**:
```bash
ac doctor
```

### `ac schema` - 显示数据库结构

显示 SQLite 数据库中所有表及其字段的定义。

```bash
ac schema
```

**示例**:
```bash
ac schema
```

### `ac features` - 列出已实现功能

展示 `ac` CLI 支持的所有功能及其实现状态。

```bash
ac features
```

**示例**:
```bash
ac features
```

### `ac config` - 管理持久化配置

设置和获取 `ac` CLI 的持久化配置，例如默认的搜索结果限制。

```bash
ac config set <key> <value>
ac config get <key>
ac config get
```

-   `<key>`: 配置项名称，例如 `limit`。
-   `<value>`: 配置项的值。

**示例**:
```bash
ac config set limit 5
ac config get limit
ac config get
```