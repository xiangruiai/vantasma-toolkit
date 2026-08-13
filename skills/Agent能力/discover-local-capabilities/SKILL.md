---
name: discover-local-capabilities
description: Scan a computer for installed Agent Skills, command-line tools, MCP servers, and local plugins, then generate a verified scene-to-tool capability map. Use when the user asks what local abilities are available, which installed tool should handle a task, to build or refresh a capability map, to audit Skills or CLI tools, or to avoid repeatedly probing with which and --help.
---

# Discover Local Capabilities

Generate an evidence-backed local capability map before choosing tools. Treat the scan result as an index, not as proof that every discovered capability is authorized or healthy.

## Workflow

1. Run the scanner from the user's current project:

   ```bash
   python3 "<skill-dir>/scripts/scan_capabilities.py" --project "$PWD" --output-dir .capability-map
   ```

2. Read `.capability-map/capability-map.md` first. Use `.capability-map/capability-map.json` when structured routing or further automation is needed.
3. Route the user's request through the “场景 → 首选能力” table before exploring tools manually.
4. Verify the selected tool at task time. A discovered executable or Skill may still lack authentication, permissions, dependencies, or network access.
5. Refresh the map after installing, removing, renaming, or upgrading Skills, CLI tools, MCP servers, or plugins.

## Optional Scans

- Add CLI versions only when needed. Version probing executes each discovered command with a safe version flag and a short timeout:

  ```bash
  python3 "<skill-dir>/scripts/scan_capabilities.py" --project "$PWD" --output-dir .capability-map --probe-versions
  ```

- Add extra Skill roots or CLI names explicitly:

  ```bash
  python3 "<skill-dir>/scripts/scan_capabilities.py" \
    --skill-root /path/to/shared-skills \
    --cli custom-cli \
    --output-dir .capability-map
  ```

## Discovery Boundaries

- Scan only known Skill roots, the current project, `PATH`, and known MCP/plugin metadata locations.
- Read Skill frontmatter only; do not load every Skill body during inventory.
- Never read `.env`, tokens, secrets, command histories, or MCP configuration values. Record MCP and plugin names only.
- Do not install, update, authorize, invoke, or delete discovered tools during scanning.
- Do not claim a tool is usable merely because a file exists. Report four separate states: discovered, version-probed, authenticated, task-verified. This scanner establishes only the first state and optionally the second.
- Redact the home directory as `~` in generated reports.

## Routing Rules

The scanner uses [routing-rules.json](references/routing-rules.json) to select a preferred local ability for common scenes. Edit that file when an organization has a different preferred stack. Keep rules ordered from fastest and most specialized to general fallbacks.

If no rule matches, place the capability under “待人工归类” instead of inventing a use case.

## Acceptance Checks

Before handing off a map, confirm:

- Both Markdown and JSON reports exist.
- Every preferred route cites an actually discovered Skill, CLI, MCP server, or plugin.
- Duplicate symlinked Skills are collapsed to one real source with all visible locations retained.
- Missing tools are marked as missing rather than silently omitted from the rule evaluation.
- Reports contain no secret values or `.env` contents.
