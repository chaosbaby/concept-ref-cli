# Plan: Universal Query Engine

**Objective**: Implement a schema-aware, universal query engine with context-aware completion hints, based on the user's `FIELD_TYPES` proposal. This will be orchestrated through a new `lxc query` command.

---

## Phase 1: Schema-Aware Query Engine

This phase focuses on making the `query` command intelligent about the database schema and the rules defined in `FIELD_TYPES`.

### Step 1.1: Create `SchemaManager`

- **Action**: Create a new class `SchemaManager` within `commands/query.py`.
- **Details**:
    - This class will connect to the database on initialization.
    - It will inspect the `sqlite_master` table to find all `source_*` tables.
    - For each table, it will use `PRAGMA table_info(...)` to get column names and their SQLite data types (e.g., `TEXT`, `INTEGER`).
    - It will store this information in a nested dictionary: `self.schema = {'table_name': {'column_name': 'SQLITE_TYPE'}}`.
    - It should also include a simple mapping from SQLite types to the `FIELD_TYPES` keys (e.g., `TEXT` -> `string`, `INTEGER` -> `integer`).

### Step 1.2: Integrate `FIELD_TYPES`

- **Action**: Add the user-provided `FIELD_TYPES` dictionary as a constant in `commands/query.py`.
- **Details**: This structure will be the single source of truth for operator and type validation.

### Step 1.3: Refactor `QueryBuilder` and `FilterParser`

- **Action**: Significantly refactor these classes to be schema-aware.
- **Details for `FilterParser`**:
    - The `parse` method should accept an instance of `SchemaManager`.
    - When parsing `table:column:op:value`, it should:
        1. Check if `table` and `column` exist using the `SchemaManager`.
        2. Determine the column's simple type (`string`, `integer`, etc.).
        3. Look up the type in `FIELD_TYPES` and validate that `op` is a valid operator for that type.
        4. If validation fails, provide a specific error message (e.g., "'gt' is not a valid operator for type 'string'").
- **Details for `QueryBuilder`**:
    - The `build_sql` method should use the type information to generate more efficient SQL.
    - For columns that are natively numeric, it should no longer use `CAST`.
    - It will rely on the `FilterParser` having already validated the inputs.

---

## Phase 2: Context-Aware Completion (Deferred)

This phase will be implemented after the core engine is working and verified.

### Step 2.1: Implement Custom Completer

- **Action**: Create a custom `shell_complete` function for the `filters` argument in the `query` command.
- **Details**:
    - The function will inspect `ctx.params['filters']` and the `incomplete` string.
    - It will parse the `incomplete` string (e.g., `dict:freq:`) to determine the context.
    - **Context: Table**: If `incomplete` is empty or has no `:`, suggest table names (e.g., `dict`, `ids`).
    - **Context: Column**: If `incomplete` is `dict:`, suggest columns for the `dict` table.
    - **Context: Operator**: If `incomplete` is `dict:freq:`, determine the type of `freq` (`integer`) and suggest its operators from `FIELD_TYPES`.
    - **Context: Value**: (Advanced) If `incomplete` is `dict:tag:is:`, suggest possible tags from the database.

---

## Phase 3: Testing

Simple command-line tests to be executed manually to verify functionality.

### Tests for Phase 1:

1.  **Numeric `gt` test**:
    ```bash
    lxc query dict:freq:gt:20000
    ```
    - **Expected**: Returns entries from `source_dict` where frequency is greater than 20000.

2.  **String `is` test**:
    ```bash
    lxc query dict:tag:is:n
    ```
    - **Expected**: Returns entries where the tag is exactly 'n'.

3.  **`between` test**:
    ```bash
    lxc query dict:freq:between:1000,2000
    ```
    - **Expected**: Returns entries with frequency between 1000 and 2000.

4.  **`in` test**:
    ```bash
    lxc query ids:char:in:a,b,c
    ```
    - **Expected**: Returns entries from `source_ids` where the character is 'a', 'b', or 'c'.

5.  **Invalid Operator Test**:
    ```bash
    lxc query dict:tag:gt:a
    ```
    - **Expected**: An error message stating that 'gt' is not a valid operator for a string type.

6.  **Invalid Column Test**:
    ```bash
    lxc query dict:nonexistent_col:is:foo
    ```
    - **Expected**: An error message stating the column does not exist.
