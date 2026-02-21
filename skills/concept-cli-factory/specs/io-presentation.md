# Spec: IO-Presentation (User Experience)

## Overview
Standards for how data enters and leaves the CLI.

## Features Included
- `stream`: Stdin/Stdout pipeline support.
- `formats`: `show`, `plain`, `json`, `ndjson`.
- `coloring`: ANSI highlighting for queries and headers.
- `padding`: Schema-aware output padding.
- `completion`: Static and dynamic shell completion.

## Standards
1. **Piping**: `stream` must not buffer more than 500 records in memory.
2. **Color Integrity**: `--plain` mode MUST strip all ANSI codes.
3. **Dynamic Completion**:
    - The `--sort-by` flag MUST provide shell completion listing all valid column names for the given table.
    - Dynamically generated filter options for text-based columns SHOULD provide shell completion for their potential values.
    - This value completion MUST be powered by an efficient, non-blocking query (e.g., `SELECT DISTINCT column FROM table WHERE column LIKE '...%' LIMIT 100`) that executes only when completion is requested by the user.
4. **Layout**: Vertical layout triggers automatically if content width > Terminal width.
5. **JSON**: Always output as a list `[]`, while `ndjson` is one object per line.
6. **Schema-Aware Padding**: 
    - All records within a single output stream MUST share the exact same set of keys.
    - This set of keys should be derived from the full table schema unless specific fields are requested via `--field`.
    - Missing values MUST be represented as `null` in `json`/`ndjson` formats and as a consistent placeholder (e.g., `N/A`) in `show`/`plain` formats.
    - This is the default, mandatory behavior for all query commands.
7. **Content Views**: For commands displaying potentially large text fields (e.g., search results), a `--full` flag MUST be provided to switch between a default `snippet` view and a `full-text` view.
