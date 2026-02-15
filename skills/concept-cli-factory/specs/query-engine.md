# Spec: Query-Engine (Search & Logic)

## Overview
Define how users interact with the data through search and advanced filtering.

## Features Included
- `search`: Core FTS5 search with weighting.
- `filter`: Multi-dimensional filtering (min-max, in-set).
- `random`: High-quality serendipity recommendations.
- `ranking`: Relevance-based sorting logic.

## Standards
1. **Weighting**: Match in 'title' > Match in 'tags' > Match in 'content'.
2. **Filtering**: All numeric fields must support `min-max` range syntax.
3. **Complexity**: Join operations should be indexed on both sides.
4. **Randomness**: Use `ORDER BY RANDOM()` with a limit to ensure performance.
