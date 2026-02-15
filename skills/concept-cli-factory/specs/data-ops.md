# Spec: Data-Ops (Data Lifecycle)

## Overview
Handle the persistence layer, integrity, and diagnostic operations of the concept database.

## Features Included
- `init`: High-performance SQLite import.
- `schema`: Self-introspection of table structures.
- `doctor`: Health and index sanity checks.
- `vacuum`: Database optimization and maintenance.

## Standards
1. **SQLite Engine**: Must use WAL mode for concurrent read/write.
2. **Indexing**: FTS5 is mandatory for searchable fields.
3. **Batch Loading**: `init` must use transactions and chunk sizes of 1000+.
4. **Validation**: Every record must pass `id` presence check before insertion.
