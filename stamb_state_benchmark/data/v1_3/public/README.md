# STAMB-State v1_3 Public Track

`events.json`, `cases.json`, `scope_profiles.json`, `scope_taxonomy.json`, and `subsets.json` are the no-gold end-to-end input files.
`scope_taxonomy.json` contains public-safe scope type, task family, and domain labels for routing and breakdown analysis.
`subsets.json` contains only case ids, not gold labels or difficulty metadata.
Evaluator-only fields are retained only in `../cases.json` and annotation files.
