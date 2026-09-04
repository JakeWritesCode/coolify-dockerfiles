"""Model-facing schema for the usage meter tool."""

USAGE_METER = {
    "name": "usage_meter",
    "description": (
        "Explicitly attribute Hermes model usage to a Forgejo issue delivery work unit. "
        "Start before issue-specific work, inspect live or finalized counts, arm finish only "
        "after a verified merge, or list active and completed records. Finalization occurs "
        "after the finish turn drains token accounting. Never infer attribution from timestamps alone."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["start", "status", "finish", "list"],
                "description": "Meter operation to perform.",
            },
            "work_unit": {
                "type": "string",
                "description": (
                    "Stable identifier such as forgejo:jake/shallwego:issue:29. "
                    "Required for start, status, and finish."
                ),
            },
            "pr_number": {
                "type": "integer",
                "minimum": 1,
                "description": "Merged pull-request number; required for finish.",
            },
            "merge_sha": {
                "type": "string",
                "pattern": "^[0-9a-fA-F]{40}$",
                "description": "Verified full merge commit SHA; required for finish.",
            },
            "limit": {
                "type": "integer",
                "minimum": 1,
                "maximum": 100,
                "default": 20,
                "description": "Maximum active and completed rows returned by list.",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    },
}
