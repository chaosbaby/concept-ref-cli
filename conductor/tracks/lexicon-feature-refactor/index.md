# Track: Lexicon Feature Standardization

## Highest Self-Consistency Goal
将 Lexicon 命令提升至 Factory 工业级标准，通过集成 Schema 自省、双向管道流和 UX 补全，确保其作为“数据零件”在 Unix 链条中的确定性与易用性。

## Status
- **Phase**: Completed ✅
- **Health**: Green 🟢

## Roadmap

### Phase 1: Feature Implementation
- [x] Implement `schema` command for DB introspection.
- [x] Enhance `search` to support `stdin` pipe input.
- [x] Add `completion` command group for shell integration.

### Phase 2: Feature Matrix Correction
- [x] Refactor `features` command to dynamically reflect implementation status.
- [x] Define "Supported", "Missing", and "Partial" states in the matrix.

### Phase 3: Verification
- [x] Verify pipe: `echo "term" | lexicon search -`
- [x] Verify schema output.
- [x] Verify completion installation flow.
