# Graph Report - .  (2026-05-07)

## Corpus Check
- 19 files · ~0 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 19 nodes · 8 edges · 6 communities detected
- Extraction: 100% EXTRACTED · 0% INFERRED · 0% AMBIGUOUS
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Cluster 0|Cluster 0]]
- [[_COMMUNITY_Cluster 1|Cluster 1]]
- [[_COMMUNITY_Cluster 2|Cluster 2]]
- [[_COMMUNITY_Cluster 3|Cluster 3]]
- [[_COMMUNITY_Cluster 4|Cluster 4]]
- [[_COMMUNITY_Cluster 10|Cluster 10]]

## God Nodes (most connected - your core abstractions)

## Surprising Connections (you probably didn't know these)
- None detected - all connections are within the same source files.

## Communities

### Community 0 - "Cluster 0"
Cohesion: 0.5
Nodes (4): Angel One (NSE broker API), Firebase, nse-delivery-bot (swing), nse-trading-bot (intraday)

### Community 1 - "Cluster 1"
Cohesion: 0.5
Nodes (4): Cloudflare account (PERSONAL — not Heavenly Secrets), YouTube Data API v3, youtube-mcp-worker (CF Worker, personal account), personal-yt (YouTube comment-mgmt for 2 personal channels)

### Community 2 - "Cluster 2"
Cohesion: 1.0
Nodes (1): Notion API

### Community 3 - "Cluster 3"
Cohesion: 1.0
Nodes (2): youtube-transcript.io API, yt-learnings (YouTube transcript library)

### Community 4 - "Cluster 4"
Cohesion: 1.0
Nodes (1): study-timer (Pomodoro / Flutter)

### Community 10 - "Cluster 10"
Cohesion: 1.0
Nodes (1): voice-to-text (utility)

## Knowledge Gaps
- **Thin community `Cluster 2`** (2 nodes): `Notion API`, `notion-mcp-server`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 3`** (2 nodes): `youtube-transcript.io API`, `yt-learnings (YouTube transcript library)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 4`** (1 nodes): `study-timer (Pomodoro / Flutter)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Cluster 10`** (1 nodes): `voice-to-text (utility)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Not enough signal to generate questions. This usually means the corpus has no AMBIGUOUS edges, no bridge nodes, no INFERRED relationships, and all communities are tightly cohesive. Add more files or run with --mode deep to extract richer edges._