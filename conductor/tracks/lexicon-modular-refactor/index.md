# Track: Lexicon Modular Refactor (Iterative Feature Edition)

Refactor Lexicon CLI using a "one feature at a time" implementation and verification strategy.

## Design Principles
- **Feature-First**: Every implementation must map to a definition in `features-manifest.json`.
- **Atomic Verification**: Each feature is tested and accepted before moving to the next.
- **Isolation**: Strictly maintain source-specific logic and storage.

## Implementation Progress
- [x] **[Infrastructure]**: Restore `features-manifest.json` with full triggers and CLI integration specs.
- [x] **[Architecture]**: Modular `LexiconStore` with per-source FTS5 tables.
- [x] **[Core-Loaders]**: Implementation of `TSVParser` and `WordFreqParser`.
- [x] **[Sub-commanding]**: Isolation of `dict` and `ids` commands.
- [x] **[Filtering]**: Parametric filtering (rank, tag, len) for `dict` source.
- [ ] **[Next: Config]**: Implement `config-manager` for persistent defaults (e.g., default output format).
- [ ] **[Next: Completion]**: Implement `auto-completion-engine` for millisecond-level prefix matching.
- [ ] **[Next: Interop]**: Refine `ndjson-output` and pipe-stream integration for all sub-commands.

## Feature Acceptance Log
- **fts-engine**: Verified via `init` and `search`.
- **sub-command-isolation**: Verified via `lexicon dict` vs `lexicon ids`.
- **param-filtering**: Verified via `dict search --rank-min`.
