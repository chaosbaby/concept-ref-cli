# Track: Lexicon Standardization & Migration

## Highest Self-Consistency Goal (最高自恰目标)
构建一套标准化的、符合 Unix 哲学的中文文化数据“零件协议”，确保每一个数据源（如词频、同义词、构件）都能作为独立的、可管道连接的流处理单元，为未来的“概念有机链接”提供确定性的底层索引。

## Status
- **Phase**: Completed ✅
- **Health**: Green 🟢

## Roadmap

### Phase 1: Protocol Standardization (协议标准化)
- [x] Refactor `factory/assets/template.py` to support `Headless Mode` (NDJSON output).
- [x] Define standard verbs: `search`, `stream`, `atoms`, `stats`.
- [x] Standardize logging and error handling for pipe-friendly execution.

### Phase 2: Data Decoupling (数据零件化)
- [x] Relocate raw data from `agent_skills` to `sources/lexicon/`.
- [x] Perform data sensing and schema definition for each source.
- [x] Standardize file formats (e.g., TSV/NDJSON).

### Phase 3: Component Implementation (工具实现)
- [x] Generate `commands/lexicon.py` using the updated template.
- [x] Implement FTS5-based `init` for all lexicon sub-modules.
- [x] Implement pipe-aware `search` and `stream` commands.
- [x] Implement `atoms` for character component lookup.

### Phase 4: Ecosystem Alignment (生态对接)
- [x] Register `lexicon` command in `setup.py`.
- [x] Verify pipe interoperability (`lexicon | next_tool`).
- [x] Document the "Parts Protocol" in `README.md`.
