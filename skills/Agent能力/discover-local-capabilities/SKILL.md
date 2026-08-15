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

   On a first setup, the command can generate its opaque installation ID. When a new identity is required, the Agent generates a fresh opaque `inst_...` installation ID; do not ask a non-technical person to design it. Pass the exact same validated value as `--installation-id "<inst-id>"` in plan and apply, and never reuse an inactive installation's ID.

5. Report every precise location returned under `paths`, the capability counts, changed Agent instruction targets and backup locations. If `cleanup_recovery_paths` is present, report those private recovery copies and do not delete them automatically. Tell the person to start a new Agent session when its instruction file changed.

Before reporting success, verify that the installed Skill directory itself contains `SKILL.md` and `scripts/capability_map.py`, then run `status` and require `installed=true` plus `healthy=true`. If an update was requested but the Skill directory is absent or incomplete, treat it as a clean-install recovery rather than reporting unrelated host diagnostics as an update failure. A missing optional CLI, a disabled optional MCP, or a harmless CLI version warning is not an installation failure unless this Skill actually requires it.

The public storage contains `本机能力地图.md`, `capability-inventory.json`, `capability-map.config.json`, and `setup-receipt.md`. The private namespace contains `capability-resolver.json` and `installation-state.json` in the OS system-data location, logically layered from public artifacts. Obsidian mode guarantees that it remains outside the Vault. Default local mode uses a hidden `.private` subtree under the same application-data root. With a custom public path, its physical relationship to that root depends on path topology; review the exact paths in the zero-write setup plan before confirmation.

## Route natural-language work

For a task needing local tools or capabilities:

1. Read `本机能力地图.md` first.
2. Preserve the person's explicit instructions, memory, existing business workflow, and project rules. The map chooses an implementation capability only after that workflow is established; it must not replace the workflow itself.
3. Match the request against its scenes and candidates. Use `route` for a structured lookup when helpful:

   ```bash
   python3 "<skill-dir>/scripts/capability_map.py" route \
     --storage "<storage-root>" --query "<task-query>" --json
   ```

4. Read the private resolver only after selecting a candidate. If the candidate is a Skill, complete-read its `SKILL.md` before acting.
5. Verify authentication, permission, dependencies, and task-level behavior before execution. 已发现不等于已认证或已验证.
6. If evidence is weak, return no reliable match instead of inventing a preference.

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

Plain `uninstall` removes managed Agent instructions, preserves data, and commits an inactive `uninstalled` lifecycle. Its old `refresh`, `migrate`, and repeated plain `uninstall` operations then refuse. If reinstalling at the same public root, the Agent must generate a fresh opaque `inst_...` installation ID and reuse that exact value in setup plan and apply.

Purge is accepted from either an active or uninstalled lifecycle. It recoverably moves the owned public artifacts and the complete owned private namespace, including resolver, state, instruction/state backups, and manifests, to the reported recovery directory. It leaves unrelated public files and other private namespaces in place. If external content changed or replaced an owned target, refuse the purge, preserve the external content, and restore this operation's managed changes where safe.

Treat purge as a separate destructive scope. Preview that exact scope first:

```bash
python3 "<skill-dir>/scripts/capability_map.py" uninstall --storage "<storage-root>" --dry-run --purge-data
```

Check that stdout reports `would_purge_data=true`. Only after a new explicit confirmation for this purge scope, run the same selector and purge flag with `--confirmed`:

```bash
python3 "<skill-dir>/scripts/capability_map.py" uninstall --storage "<storage-root>" --confirmed --purge-data
```

Never preview plain `uninstall` and then add `--purge-data` only at apply time. Recoverable purge currently requires public storage and private recovery to be on the same filesystem. Otherwise the command fails with `cross-filesystem purge is unsupported; migrate public storage to the private recovery filesystem before purge`, conservatively refuses the operation, and restores the installation.

For an active installation, first migrate its public storage onto the private recovery filesystem, then rerun the exact purge preview and confirmation flow. An uninstalled installation refuses `migrate`; safely preserve its recovery and data, then either have the Agent generate a new opaque `inst_...` installation ID for a reinstall or let the person review the exact paths previously returned by `setup` or `paths` and manage those files manually. Never automate deletion in this fallback.

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
- Persisted public artifacts contain sanitized capability data. Private resolver and state files persist exact local paths. The `setup` and `paths` stdout intentionally returns exact operational locations at the person's request; treat that stdout as private operational output, not as a shareable public artifact.
- Do not install, authorize, update, invoke, or delete discovered capabilities as part of discovery.

## Troubleshoot safely

- Run `status` first. Distinguish `installed` from `healthy`; report `lifecycle` and every `health_errors` item.
- Run `paths` to report exact locations after setup.
- If the plan hash is stale, discard it, rerun `setup plan`, and request fresh confirmation.
- If managed instruction markers conflict or are damaged, stop and show the diagnostics. Do not repair user content automatically.
- After migration, operate only on the new storage; the old lifecycle is `migrated` and its mutating commands must refuse.
- After plain uninstall, report `lifecycle=uninstalled`, `installed=false`, `healthy=false`, and an empty healthy-error list; use purge or a new installation ID for the next transition.
- If a successful mutation returns `cleanup_recovery_paths`, the new target is committed but an old no-clobber claim could not be removed. Preserve and report it for manual review; do not reinterpret the successful commit as a reason to roll back.
- If routing returns no reliable candidate, inspect the sanitized inventory and keep unknown capabilities unclassified.

Discovery and the normal lifecycle are supported on macOS and Linux with the POSIX directory-handle backend. Windows has a functional best-effort path backend: it checks file IDs before and after reads, rejects observed symlinks, junctions, and other reparse points, and commits through same-directory no-clobber renames with rollback copies. These Windows checks are path-based rather than handle-bound, so they cannot exclude every check/use race. A replacement can also inherit the directory ACL instead of preserving a target-specific ACL. Keep the private root inside an ACL-restricted per-user system-data directory, review custom-root permissions, and do not describe `status` as an effective Windows ACL audit; it validates schema and ownership relationships only. Recoverable `--purge-data` still requires the POSIX directory-handle backend and therefore fails closed on Windows; plain uninstall remains supported and preserves all data.
