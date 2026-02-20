# Spec: IO-Presentation (User Experience)

## Overview
Standards for how data enters and leaves the CLI.

## Features Included
- `stream`: Stdin/Stdout pipeline support.
- `formats`: `show`, `plain`, `json`, `ndjson`.
- `coloring`: ANSI highlighting for queries and headers.
- `completion`: Dynamic Shell completion for tags/categories.

## Standards
1. **Piping**: `stream` must not buffer more than 500 records in memory.
2. **Color Integrity**: `--plain` mode MUST strip all ANSI codes.
3. **Layout**: Vertical layout triggers automatically if content width > Terminal width.
4. **JSON**: Always output as a list `[]`, while `ndjson` is one object per line.
5. **Content Views**: For commands displaying potentially large text fields (e.g., search results), a `--full` flag MUST be provided to switch between a default `snippet` view and a `full-text` view.
