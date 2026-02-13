# Track: Lexicon Advanced Refactor (Industrial Protocol)

## Goal
升级 `lexicon` 及 `factory` 模板至“工业级数据协议”标准，支持标准化输入输出、虚拟 Schema 映射、极速补全及 FTS5 全文检索。

## Status
- **Phase**: Completed ✅
- **Health**: Green 🟢

## Roadmap

### Phase 1: Template Protocol Upgrade
- [x] Refactor `template.py` to support `--output/-o` (view, json, plain, stream).
- [x] Add field projection support `--field/-f`.
- [x] Standardize `stdin` handling in `search` command.
- [x] Implement `completion_table` logic for fast Shell Tab.

### Phase 2: Lexicon Schema Mapping
- [x] Update `lexicon.py` to use virtual columns (`pk`, `desc`, `tags`, `val`).
- [x] Implement FTS5 for dictionary and atoms.
- [x] Consolidate `init` logic to build the `completion_table`.

### Phase 3: CLI Interface Polish
- [x] Test `echo 逻辑 | lexicon search -`.
- [x] Verify field filtering: `lexicon search 逻辑 -f term -f semantic_codes`.
- [x] Measure completion latency (target < 50ms).

### Phase 4: Final Verification
- [x] Update `doctor` to report on FTS and completion index status.
- [x] Final documentation update.
