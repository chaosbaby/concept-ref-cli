# Implementation Plan - xh-enhancement

## Step 1: Schema Reflection [DONE]
- Add `schema` command to `commands/xh/main.py`.
- Query `sqlite_master` to list tables and columns.
- **Verification**: Run `xh schema` and check output.

## Step 2: Health Diagnosis [DONE]
- Add `doctor` command to `commands/xh/main.py`.
- Calculate record counts for `idiom`, `word`, `ci`, `xiehouyu`.
- **Verification**: Run `xh doctor`.

## Step 3: FTS5 Engine Upgrade [DONE]
- Update `init` command to create FTS5 virtual tables.
- Update `search` command to use `MATCH` instead of `LIKE`.
- **Verification**: Re-init DB and run `xh search`.

## Step 4: Rich Render Engine [DONE]
- Implement a `formatter` to handle multi-line explanations and highlights.
- Integrate into `idiom`, `word`, and `ci` commands.
- **Verification**: Run `xh idiom 登高望远` and check formatting.

## Step 5: Interactive Pick [DONE]
- Add `pick` command.
- Use `ORDER BY RANDOM()` to fetch records.
- **Verification**: Run `xh pick`.
