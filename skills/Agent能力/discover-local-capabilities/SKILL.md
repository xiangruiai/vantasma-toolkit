---
name: discover-local-capabilities
description: Discover the installer's local Agent Skills, PATH CLIs, MCP servers, and plugins; generate or refresh a neutral capability map; and route natural-language tasks through verified local evidence. Use when someone asks what this computer can do, which installed capability fits a task, where the capability map is stored, or how to set up, refresh, migrate, audit, or uninstall local capability routing.
---

# Discover Local Capabilities

Use the command entrypoint at `"<skill-dir>/scripts/capability_map.py"`. Prefer a natural-language conversation: translate the person's intent into the commands below, show the result, and explain the next safe action.

## Set up the routing loop

1. Ask the person to choose all three dimensions before planning:

   - Storage: local default directory, Obsidian Vault, or custom directory.
   - Agent: `--agents codex|claude|both`.
   - Scope: `--scope user|project`.

2. Run `setup plan` with the selected values. This phase is read-only and guarantees zero writes. Use one storage form:

   ```bash
   # Local default directory: omit --storage and --vault
   python3 "<skill-dir>/scripts/capability_map.py" setup plan \
     --agents both --scope user --project "<project-root>"

   # Obsidian Vault
   python3 "<skill-dir>/scripts/capability_map.py" setup plan \
     --vault "<vault-root>" --agents both --scope user \
     --project "<project-root>"

   # Custom directory
   python3 "<skill-dir>/scripts/capability_map.py" setup plan \
     --storage "<storage-root>" --agents codex --scope project \
     --project "<project-root>"
   ```

3. Show the plan's absolute paths, file and instruction changes, backups, warnings, counts, and `plan_hash`. Ask for当次明确确认. Planning permission is not apply permission.

4. Only after that confirmation, rerun the identical selection with `setup apply`, `--confirmed`, and the returned `--expected-plan-hash`. Never reuse an old confirmation or hash.

   ```bash
   python3 "<skill-dir>/scripts/capability_map.py" setup apply \
     --storage "<storage-root>" --agents codex --scope project \
     --project "<project-root>" --confirmed \
     --expected-plan-hash "<plan-hash>"
   ```

   Normally let setup generate its opaque installation ID. Only preserve an existing integration when explicitly required by passing the same validated `--installation-id "<inst-id>"` to plan and apply; the value must start with `inst_`.

5. Report every precise location returned under `paths`, the capability counts, changed Agent instruction targets and backup locations. Tell the person to start a new Agent session when its instruction file changed.

The public storage contains `本机能力地图.md`, `capability-inventory.json`, `capability-map.config.json`, and `setup-receipt.md`. The private namespace contains `capability-resolver.json` and `installation-state.json`; it is always layered separately from public artifacts and never enters Obsidian. In default local mode it is a hidden `.private` subtree under the same application-data root. In custom-directory and Obsidian modes it is outside the selected public root.

## Route natural-language work

For a task needing local tools or capabilities:

1. Read `本机能力地图.md` first.
2. Match the request against its scenes and candidates. Use `route` for a structured lookup when helpful:

   ```bash
   python3 "<skill-dir>/scripts/capability_map.py" route \
     --storage "<storage-root>" --query "<task-query>" --json
   ```

3. Read the private resolver only after selecting a candidate. If the candidate is a Skill, complete-read its `SKILL.md` before acting.
4. Verify authentication, permission, dependencies, and task-level behavior before execution. 已发现不等于已认证或已验证.
5. If evidence is weak, return no reliable match instead of inventing a preference.

Use the generic bilingual taxonomy in [`references/scene-taxonomy.json`](references/scene-taxonomy.json). It defines scene semantics, not concrete preferred tools.

## Operate the map

Use the same `--storage <storage-root>` or `--vault <vault-root>` selector that identifies the active installation.

```bash
python3 "<skill-dir>/scripts/capability_map.py" status --storage "<storage-root>"
python3 "<skill-dir>/scripts/capability_map.py" paths --storage "<storage-root>"
python3 "<skill-dir>/scripts/capability_map.py" refresh --storage "<storage-root>" --dry-run
python3 "<skill-dir>/scripts/capability_map.py" refresh --storage "<storage-root>" --confirmed
python3 "<skill-dir>/scripts/capability_map.py" migrate --storage "<storage-root>" --to "<new-storage-root>" --dry-run
python3 "<skill-dir>/scripts/capability_map.py" migrate --storage "<storage-root>" --to "<new-storage-root>" --confirmed
python3 "<skill-dir>/scripts/capability_map.py" uninstall --storage "<storage-root>" --dry-run
python3 "<skill-dir>/scripts/capability_map.py" uninstall --storage "<storage-root>" --confirmed
```

`uninstall` removes only managed Agent instructions and preserves map data. Preview and obtain a separate当次明确确认 before adding `--purge-data`; purge moves data to a reported recovery directory.

Interpret a help request without touching an installation:

```bash
python3 "<skill-dir>/scripts/capability_map.py" help-intent --query "能力地图放在哪里"
```

## Run a standalone scan

Without `--output-dir`, `scan` returns a sanitized inventory on stdout and writes nothing. Writing a scan bundle requires explicit confirmation:

```bash
python3 "<skill-dir>/scripts/capability_map.py" scan --project "<project-root>"
python3 "<skill-dir>/scripts/capability_map.py" scan --project "<project-root>" \
  --output-dir "<storage-root>" --confirmed
```

Add `--skill-root "<extra-skill-root>"` for an extra source. Only add `--probe-versions explicit` after explaining that it executes bounded version probes; the default does not execute discovered CLIs.

## Preserve privacy and neutrality

- Scan the installer's computer. Do not inject a packaged capability snapshot, concrete preferred-tool list, or another person's preferences.
- Default to no network access and no execution of discovered CLIs.
- Do not read `.env`, credential stores, or command histories. Supported MCP configuration files are parsed with size bounds, but secret values, command, args, URL, headers, and env fields are not collected, persisted, or emitted.
- Keep exact local paths only in the private resolver and runtime state. Treat public artifacts as reviewable but still potentially sensitive inventory.
- Do not install, authorize, update, invoke, or delete discovered capabilities as part of discovery.

## Troubleshoot safely

- Run `status` first. Distinguish `installed` from `healthy`; report `lifecycle` and every `health_errors` item.
- Run `paths` to report exact locations after setup.
- If the plan hash is stale, discard it, rerun `setup plan`, and request fresh confirmation.
- If managed instruction markers conflict or are damaged, stop and show the diagnostics. Do not repair user content automatically.
- After migration, operate only on the new storage; the old lifecycle is `migrated` and its mutating commands must refuse.
- If routing returns no reliable candidate, inspect the sanitized inventory and keep unknown capabilities unclassified.

Discovery is designed for macOS, Linux, and Windows roots and executable conventions. Transactional setup has its strongest guarantees on POSIX systems because it relies on secure directory-fd, no-follow, atomic replacement, and `0600` semantics. On Windows those primitives can be unavailable, so setup may fail closed; do not claim durable Agent integration until the environment passes its own setup and status checks.
