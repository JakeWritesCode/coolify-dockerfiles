# Hermes usage meter

This standalone Hermes plugin attributes model usage to an explicitly opened Forgejo issue work unit. It reads `$HERMES_HOME/state.db` in read-only mode and stores active baselines plus finalized merge records in:

```text
$HERMES_HOME/plugin-data/usage-meter/usage-meter.db
```

The separate analytics database uses SQLite WAL mode. It is not committed and survives plugin updates because it lives in Hermes' profile-scoped plugin data directory.

## Install in this Coolify stack

`hermes/Dockerfile.agent` bakes the plugin into the Hermes image outside both persistent mounts. Its entrypoint copies the plugin into the profile home on every container start:

```text
/home/hermes/.hermes/plugins/usage-meter
```

This avoids runtime bind mounts into Coolify's temporary source checkout, which is removed after deployment. After deploying the Compose change, enable the plugin once in the Hermes container/profile and restart the gateway:

```sh
hermes plugins enable usage-meter
```

Then confirm it loads:

```sh
hermes plugins doctor "$HERMES_HOME/plugins/usage-meter" --ci
hermes plugins list
```

The plugin exposes the deferred `usage_meter` tool and the explicitly loadable `usage-meter:usage-meter` skill. It also injects a short cache-safe discovery instruction into every new session, so agents know to resolve the deferred tool through `tool_search` → `tool_describe` → `tool_call` instead of incorrectly declaring it unavailable.

## Operations

```json
{"action":"start","work_unit":"forgejo:jake/shallwego:issue:29"}
{"action":"status","work_unit":"forgejo:jake/shallwego:issue:29"}
{"action":"finish","work_unit":"forgejo:jake/shallwego:issue:29","pr_number":57,"merge_sha":"72332d64bf3d8da272f4ea78a5389769ccbaf516"}
{"action":"list","limit":20}
```

`finish` arms an end-of-turn finalizer instead of snapshotting immediately. Hermes drains queued token/cost counters before the plugin's `post_llm_call` hook seals the immutable merge record. Call `status` in the next turn to receive `pr_comment_markdown`, which contains a human-readable summary and a `hermes-merge-usage:v1` marker. Posting remains the responsibility of the repository's authenticated Forgejo helper.

## Attribution model

The start snapshot covers the current parent session and records its stable conversation-lineage root to prevent a compression continuation from opening an overlapping work unit. Live and final reports subtract that baseline and recursively include later:

- compression continuations; and
- delegated child sessions whose `_delegate_from` chain reaches the metered parent.

Branch, reset, tool-child, pre-start, and unrelated sessions are excluded. Usage remains decomposed by provider, model, billing mode, and Hermes task.

## Local tests

From the repository root:

```sh
python3 -m unittest discover -s hermes/plugins/usage-meter/tests -v
```
