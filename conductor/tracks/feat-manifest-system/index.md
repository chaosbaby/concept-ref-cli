# Track: Feature Manifest System

Establish a manifest-driven development flow for the Concept CLI Factory.

## Tasks
- [x] Create `factory/references/features-manifest.json` with 10 core features.
- [ ] Implement `factory/scripts/feature_detector.py` to match features against data.
- [ ] Update `factory/assets/template.py` to include `features` command in generated CLIs.
- [ ] Add `features` command to the Skill's internal logic for interactive guidance.

## Success Criteria
- Running `<tool> features` displays a formatted table of capabilities.
- The Skill can proactive suggest features based on the manifest.
