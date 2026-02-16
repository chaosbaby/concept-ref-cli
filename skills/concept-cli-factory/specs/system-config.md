# Spec: System-Config (Infrastructure)

## Overview
Managing the tool's internal state and self-documentation.

## Features Included
- `config`: Persistent user preferences.
- `features`: Feature status matrix (from manifest).
- `readme`: Auto-generation of usage documentation.

## Standards
1. **Persistence**: Config must be stored in `~/.<tool_id>.json`.
2. **Feature Tracking**: `features` must reflect `features-manifest.json` in real-time.
3. **Ranks**: Manifest must use `rank` field to sort features in `features` output.
4. **Documentation**: Help text must be dynamically generated from command docstrings.
