# Spec: Dynamic Schema Adapter

## Overview
Defines a runtime mechanism that automatically generates CLI filter options by introspecting a database table's schema. This eliminates hardcoded parameters and ensures the CLI stays synchronized with the data structure.

## Features Included
- `schema-reflection`: Runtime introspection of table columns and types.
- `dynamic-option-injection`: Dynamically attaching `click.Option` to a command based on schema.
- `smart-completion`: Automatic shell completion for low-cardinality text fields.
- `boolean-logic-switching`: Support for toggling between `AND` and `OR` for combining filters.

## Standards

1.  **Introspection Mechanism**: The adapter MUST use `PRAGMA table_info(table_name)` to fetch column names and their data types (`INTEGER`, `REAL`, `TEXT`, etc.).

2.  **Type-to-Parameter Mapping**:
    *   **Numeric (`INTEGER`, `REAL`)**: MUST be mapped to a `--<column-name>` option that uses a `RangeParser`. The parser must support single values (`10`), ranges (`10-20` or `10-`), and comma-separated values (`10,20` interpreted as a range).
    *   **Text (`TEXT`)**: MUST be mapped to a `--<column-name>` option for exact or `LIKE` matching.
    *   **Tag Fields**: For `TEXT` fields identified as "tags" (or with a unique value count below 100), the CLI option MUST have `shell_complete` enabled to provide dynamic completion.

3.  **Dynamic Injection**:
    *   Options MUST be injected at runtime before the Click application runs. This can be achieved via a factory function that constructs the command or by manipulating the `command.params` list.
    *   The system MUST avoid generating options for primary keys or internal FTS5 columns.

4.  **SQL Query Construction**:
    *   The query builder MUST dynamically add `WHERE` clauses for each filter option provided by the user.
    *   A global `--or` flag MUST be provided. When present, it switches the logical operator between different field filters from the default `AND` to `OR`.

5.  **Output Field Selection**: The `search` command must retain the `-f` / `--field` option to allow users to select specific columns for the final output, compatible with the dynamically generated filters.
