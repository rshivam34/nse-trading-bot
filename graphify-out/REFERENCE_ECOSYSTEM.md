# Graph Report - .  (2026-05-01)

## Corpus Check
- 13 files · ~0 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 13 nodes · 4 edges · 5 communities detected
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Cluster 0|Cluster 0]]
- [[_COMMUNITY_Cluster 1|Cluster 1]]
- [[_COMMUNITY_Cluster 2|Cluster 2]]
- [[_COMMUNITY_Cluster 3|Cluster 3]]
- [[_COMMUNITY_Cluster 9|Cluster 9]]

## God Nodes (most connected - your core abstractions)

## Surprising Connections (you probably didn't know these)
- `nse-trading-bot (intraday)` --uses_broker_api--> `Angel One (NSE broker API)`  [EXTRACTED]
  nse-trading-bot/ → (external)  _Bridges community 1 → community 2_

## Communities

### Community 0 - "Cluster 0"
Cohesion: 1.0
Nodes (1): Notion API

### Community 1 - "Cluster 1"
Cohesion: 1.0
Nodes (2): Firebase, nse-trading-bot (intraday)

### Community 2 - "Cluster 2"
Cohesion: 1.0
Nodes (2): Angel One (NSE broker API), nse-delivery-bot (swing)

### Community 3 - "Cluster 3"
Cohesion: 1.0
Nodes (1): study-timer (Pomodoro / Flutter)

### Community 9 - "Cluster 9"
Cohesion: 1.0
Nodes (1): voice-to-text (utility)

## Knowledge Gaps
- **Thin community `Cluster 0`** (2 nodes): `Notion API`, `notion-mcp-server`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 1`** (2 nodes): `Firebase`, `nse-trading-bot (intraday)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 2`** (2 nodes): `Angel One (NSE broker API)`, `nse-delivery-bot (swing)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 3`** (1 nodes): `study-timer (Pomodoro / Flutter)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 9`** (1 nodes): `voice-to-text (utility)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Not enough signal to generate questions. This usually means the corpus has no AMBIGUOUS edges, no bridge nodes, no INFERRED relationships, and all communities are tightly cohesive. Add more files or run with --mode deep to extract richer edges._