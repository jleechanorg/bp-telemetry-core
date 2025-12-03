---
name: telemetry-insights
description: Analyze AI coding session telemetry for usage patterns, token efficiency, and workflow optimization. Supports current session or historical time periods.
---

# Telemetry Insights

## Scope Detection

| User Request | Scope |
|--------------|-------|
| "How efficient am I?" | Current session |
| "Analyze this conversation" | Current session |
| "this week" / "last 7 days" | 7 days |
| "today" / "last 24 hours" | 1 day |
| "last month" | 30 days |
| "productivity" / "project" / "traces" | 7 days (default historical) |

---

## Data Access

**Database**: `~/.blueplane/telemetry.db`

**Tables**: `cursor_raw_traces`, `claude_raw_traces`

### Platform Data Availability

| Field | Cursor | Claude Code |
|-------|--------|-------------|
| Tokens | ✅ `tokenCount.inputTokens/outputTokens` | ✅ `message.usage` |
| Model | ❌ Not stored by Cursor | ✅ `message.model` |
| Prompt text | ✅ `text` field | ✅ Transcript entries |

### Workspace Filtering for Bubbles

Bubble events have empty `workspace_hash`. To filter by workspace:

1. Get valid `composer_id`s from composer events with target `workspace_hash`
2. Extract `composer_id` from bubble's `item_key`: `bubbleId:{composerId}:{bubbleId}`
3. Filter bubbles to those with matching composer_id

```sql
-- Get composer_ids for workspace
SELECT DISTINCT composer_id FROM cursor_raw_traces
WHERE event_type = 'composer' AND workspace_hash = ? AND workspace_hash != '';

-- Then filter bubbles by composer_id extracted from item_key
```

### Message Types

- `type=1`: User prompt
- `type=2`: AI response (has `tokenCount`)

---

## Raw Metrics

### A. Flow & Structure
- `analysis_scope`, `session_duration`, `active_exchanges`, `total_ai_responses`
- `context_switch_count`, `prompt_timing_buckets`, `session_summaries`

### B. Prompting Patterns
- `prompt_count`, `average_prompt_length`, `median_prompt_length`
- `prompt_complexity_score` (low/medium/high), `reprompt_loop_count`

### C. Token Economics
- `total_input_tokens`, `total_output_tokens`, `input_output_ratio`
- `estimated_cost_usd`: `(input/1M × $3) + (output/1M × $15)`

### D. Patch Behavior
- `patch_count`, `total_lines_added`, `total_lines_removed`, `add_remove_ratio`

### E. Behavioral Signals
- `delegation_style`: high-level vs step-by-step indicators
- `positive_feedback` / `negative_feedback` counts

### F. Capability Usage
- `capabilities_invoked`, `agentic_mode_usage`

### G. Model Strategy (Claude Code only)
- `per_model_usage`, `per_model_tokens`, `dominant_model`

### H. Temporal Productivity
- `tokens_per_day`, `tokens_per_hour_utc`, `prompts_per_minute_by_session`

---

## Derived Insights

1. **Effort_vs_Progress_Score** (0-1): lines_added / total_tokens
2. **Context_Sufficiency_Index** (0-1): 1 - (corrections / prompts)
3. **AI_Utilization_Quality_Score** (0-1): weighted agentic + efficiency + success
4. **Predicted_Task_Difficulty**: easy/moderate/hard based on query rate, switches
5. **AI_vs_Human_Burden_Ratio**: ai_output_chars / user_input_chars
6. **Persistence_vs_Abandonment**: reprompt loops vs topic abandonment
7. **Patch_Efficiency_Curve**: clean (ratio>3) vs thrashy, lines_per_prompt
8. **Intent_Shift_Map**: task type transitions count
9. **Prompt_Quality_vs_Result**: success rate by prompt length
10. **Confidence_Trajectory**: improving/declining/mixed
11. **Stuckness_Prediction**: risk_level based on correction rate, loops
12. **Prompt_Pacing_Profile**: rapid_iterator/balanced/deliberate
13. **Model_Strategy_Assessment**: single_model/tiered_models, cost_awareness
14. **Peak_Performance_Windows**: top hours UTC
15. **Session_Focus_Profile**: short_bursts/long_deep_work/mixed

---

## Output Format

```
1. RAW_METRICS: { JSON with metrics A-H above }

2. DERIVED_INSIGHTS: { JSON with insights 1-15 above }

3. SESSION_SUMMARY: 6-10 sentences covering:
   - Analysis scope (first sentence)
   - Duration and activity level
   - Workflow patterns
   - Token efficiency
   - Key recommendations
```

---

## Interpretation Guidelines

| Input:Output Ratio | Assessment |
|--------------------|------------|
| < 10:1 | Excellent |
| 10-25:1 | Normal |
| 25-50:1 | Context-heavy |
| > 50:1 | Inefficient |

### Recommendation Triggers

| Signal | Recommendation |
|--------|----------------|
| 0% agentic usage | Enable agentic mode for multi-file tasks |
| >50:1 ratio frequently | Start new conversations for simple queries |
| High negative feedback | Provide more context upfront |
| High context switches | Consider task batching |

---

## Limitations

- Model info unavailable for Cursor (platform limitation)
- Token counts depend on capture completeness
- Task type inference is keyword-based (heuristic)
- Cost estimates based on Claude 3.5 Sonnet pricing
