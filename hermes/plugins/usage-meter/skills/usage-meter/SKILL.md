---
name: usage-meter
description: Attribute delivery usage with explicit work units.
version: 0.1.0
author: Jake (JakeWritesCode), Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [usage, delivery, forgejo, analytics]
    related_skills: []
---

# Usage Meter

Attribute model usage to one delivery by explicitly opening and closing a work unit. The meter reads Hermes session counters and descendants; it does not infer ownership from issue, pull-request, or wall-clock timestamps.

## When to Use

- Start when beginning implementation, research, review, CI diagnosis, deployment, or regression work for a specific Forgejo issue.
- Check counts during delivery or before a hand-off.
- Finish after the pull request is verifiably merged at an exact SHA.
- List records when auditing active or completed deliveries.
- Do not use it for routine application inference, unrelated chat, pre-issue research, or later defects tracked as separate issues.

## Prerequisites

- The `usage-meter` plugin is installed and enabled in the active Hermes profile.
- The current conversation is the parent/orchestrator session for the delivery.
- Use a stable work unit shaped as `forgejo:<owner>/<repository>:issue:<number>`.
- Before finishing, read back the merged pull request and its full 40-character merge SHA from Forgejo.

## Quick Reference

Call `usage_meter` with:

- Start: `{"action":"start","work_unit":"forgejo:jake/shallwego:issue:29"}`
- Counts: `{"action":"status","work_unit":"forgejo:jake/shallwego:issue:29"}`
- Finish: `{"action":"finish","work_unit":"forgejo:jake/shallwego:issue:29","pr_number":57,"merge_sha":"<40-char-sha>"}`
- List: `{"action":"list","limit":20}`

## Procedure

1. Call `usage_meter` with `action=start` before issue-specific work. Confirm the response names the intended repository, issue, and current root session.
2. Keep unrelated work outside the metered parent conversation. Delegated child sessions and compression continuations are included automatically when their recorded lineage reaches the parent.
3. Call `usage_meter` with `action=status` at meaningful hand-offs when a live count is useful. Preserve the decomposed token, cost, model, task, and session dimensions; do not replace them with one combined token number.
4. Verify the pull request is merged and read back its exact merge commit. Never substitute the reviewed head SHA when the forge produced a distinct merge commit.
5. Call `usage_meter` with `action=finish`, the PR number, and the full merge SHA. Confirm it returns `status=closing`, then end the current turn so Hermes can drain queued usage and seal the record through `post_llm_call`.
6. In the next turn, call `usage_meter` with `action=status`. Confirm it returns `status=finished`, the exact merge SHA, and `pr_comment_markdown`.
7. Post exactly the returned `pr_comment_markdown` to the merged pull request using the repository-owned Forgejo workflow. Read the comment back and verify the `hermes-merge-usage:v1` marker before declaring delivery complete.

## Counting Contract

Count the entire delivery cost attributable to the issue:

- parent/orchestrator calls;
- implementation, review, and fix subagents;
- issue-specific research;
- CI diagnosis;
- deployment and runtime verification; and
- regression work completed before delivery is declared complete.

Record later escaped regressions under their own issue work units. A future reporting layer may roll those into an adjusted delivery cost without overwriting the original record.

## Pitfalls

- A work unit cannot be restarted or finished twice, and one conversation lineage cannot hold two open work units. Inspect existing records with `status` or `list`; use a separate Hermes session when two issues genuinely overlap.
- Starting after work begins undercounts it; finishing before verified delivery omits later verification calls.
- One conversation can contain unrelated work. Explicit attribution is still a process boundary, not content classification.
- Cached input and reasoning may already be included in provider billing totals. Keep raw dimensions separate and do not sum them into a claimed billing total.
- `actual_cost_usd=null` means Hermes had no actual-cost evidence; zero is not silently treated as actual. Likewise, `estimated_cost_usd=null` means pricing was unknown, while an included or genuinely estimated zero-cost route remains `0`.
- The v1 meter emits comment Markdown but does not own Forgejo credentials or post comments itself.

## Verification

A completed delivery is metered only when all of these are true:

- `usage_meter finish` succeeded for the intended work unit;
- `merge_usage` contains the exact repository, issue, PR, and merge SHA;
- model/task breakdown and attributed session IDs remain present in the durable record; and
- the merged pull request contains one read-back-verified `hermes-merge-usage:v1` comment.
