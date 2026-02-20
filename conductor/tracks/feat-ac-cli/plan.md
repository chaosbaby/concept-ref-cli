# Plan: AI-Chat (ac) CLI Implementation

## Phase 1: Scaffolding (规范激活)
- [x] 初始化 `commands/ac/` 目录
- [x] 创建 `commands/ac/manifest.json` (定义特性矩阵)
- [x] 基于模板生成 `commands/ac/main.py`
- [ ] 注册子命令至 `setup.py` (若需要)

## Phase 2: Data & Sync (Data-Ops)
- [x] 设计 SQLite Schema (sessions, messages)
- [x] 实现数据同步逻辑 (`sync`): 增量导入 `sources/ai-chat/conversations/*.json`
- [x] 实现多源解析器 (DeepSeek/Gemini/Generic)

## Phase 3: Search & IO (Query-Engine & Presentation)
- [x] 实现 FTS5 全文检索逻辑
- [x] 完善四大输出协议: `show`, `plain`, `json`, `ndjson`
- [x] 实现搜索高亮 (Show 模式)
- [x] 实现 Unix 管道流 (pipe-stream)
- [x] 实现智能排版引擎 (rich-render-engine)

## Phase 4: Factory Standards
- [x] 实现 `features` 命令 (动态读取 manifest)
- [x] 实现 `doctor` 与 `schema` 指令
- [x] 实现 `config` 指令 (持久化偏好)

## Phase 5: Verification
- [ ] 执行 `ac doctor` 与搜索测试
- [ ] 生成 `README.md`
