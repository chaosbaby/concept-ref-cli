# Spec: Query-Engine (Search & Logic)

## Overview
Define how users interact with the data through search and advanced filtering.

## Features Included
- `search`: Core FTS5 search with weighting.
- `filter`: Multi-dimensional filtering (min-max, in-set).
- `ranking`: Relevance-based sorting logic.
- `sorting`: User-defined column sorting.
- `random`: High-quality serendipity recommendations.


## Standards
1. **Weighting**: Match in 'title' > Match in 'tags' > Match in 'content'.
2. **Filtering**: All numeric fields must support `min-max` range syntax (`1-100`, `10-`, `-50`).
3. **Sorting**:
    - A `--sort-by [COLUMN]` flag MUST be provided.
    - A `--sort-dir [asc|desc]` flag MUST be provided, defaulting to `desc`.
    - The value for `--sort-by` MUST be validated against the table's column names to prevent injection.
    - A sensible default sort order (e.g., by a `create_time` or `id` column) MUST be implemented when no flag is provided.
4. **Complexity**: Join operations should be indexed on both sides.
5. **Randomness**: Use `ORDER BY RANDOM()` with a limit to ensure performance.
