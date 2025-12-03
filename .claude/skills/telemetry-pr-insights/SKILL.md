---
name: telemetry-pr-insights
description: Concise, PR-friendly telemetry reports scoped to current branch lifetime. For CI/automation.
---

# Telemetry PR Insights

## Scope

### Default: Branch Lifetime

1. Find merge-base: `git merge-base HEAD origin/main`
2. Get timestamp: `git show -s --format=%cI <merge_base>`
3. Query events where `timestamp >= branch_start` for current workspace

### Fallback: Last 7 Days

If Git unavailable or merge-base fails.

---

## Data Access

**Database**: `~/.blueplane/telemetry.db`

### Workspace Filtering

Bubbles have empty `workspace_hash`. Join via `composer_id`:

1. Get `composer_id`s from composers with target `workspace_hash`
2. Extract `composer_id` from bubble `item_key`: `bubbleId:{composerId}:{bubbleId}`
3. Filter bubbles to matching composer_ids

### Platform Limitations

| Field | Cursor | Claude Code |
|-------|--------|-------------|
| Tokens | ✅ | ✅ |
| Model | ❌ Not stored | ✅ |

---

## Metrics (Lean Subset)

```json
{
  "window": { "analysis_scope": "branch_pr|time_period", "branch_name": "...", "branch_start": "..." },
  "activity": { "total_prompts": N, "total_ai_responses": N, "active_days": N, "sessions": N },
  "tokens": { "total_input": N, "total_output": N, "ratio": "X.XX", "per_day": {...} },
  "sessions": { "short": N, "long": N, "avg_prompts_per_session": N }
}
```

---

## Derived Insights (3-5 max)

- **Efficiency**: overall ratio, assessment (low/normal/high)
- **Activity Pattern**: steady/bursty/spiky
- **Model Strategy**: dominant model, cost awareness (Claude Code only)

---

## Output Format

### Executive Summary (2-4 sentences)

**First sentence MUST state time frame**:
- "Since this branch diverged from `main` on YYYY-MM-DD, ..."
- "Over the last 7 days, ..."

Then: activity level, efficiency, standout patterns.

### Key Metrics (compact)

- Total prompts / responses
- Input/output tokens and ratio
- Per-day snapshot (3-5 days max)

### Recommendations (3-5 bullets)

Pragmatic, low-risk suggestions. No personal commentary.

---

## Privacy

- Never include raw code content
- No verbatim prompts/responses
- Focus on aggregated metrics only
