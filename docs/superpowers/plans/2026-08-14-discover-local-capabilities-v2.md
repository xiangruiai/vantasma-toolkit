# discover-local-capabilities v2 Implementation Plan

> **For agent execution:** Use `superpowers:subagent-driven-development`. For every task, follow RED → GREEN → REFACTOR, then run a spec-compliance review before a code-quality review. Do not begin the next task while either review has open findings.

**Goal:** Replace the repository's author-biased capability scanner with a neutral, cross-platform system that inventories the installer's local Skills, CLI commands, MCP servers, and plugins; writes a concise capability map plus a sanitized inventory; optionally stores the public files in a chosen local or Obsidian directory; and installs reversible Agent routing instructions only after a hash-bound confirmation.

**Architecture:** A standard-library Python 3.10+ package separates discovery, normalization, sanitization, classification, rendering, storage, and managed instruction transactions. Public output contains only sanitized metadata and opaque resolver IDs. Exact paths live in a private resolver index outside any selected Vault. A command entrypoint exposes scan, setup, status, paths, refresh, route, migrate, and uninstall workflows; the old script remains as a compatibility wrapper.

**Tech Stack:** Python standard library (`argparse`, `dataclasses`, `hashlib`, `json`, `os`, `pathlib`, `plistlib`, `re`, `shutil`, `stat`, `tempfile`, `tomllib`, `unittest`), Markdown, YAML metadata files.

**Design source:** `docs/superpowers/specs/2026-08-14-discover-local-capabilities-v2-design.md`

**Target package:** `skills/Agent能力/discover-local-capabilities`

## Global constraints

- Never inspect or read `.env` files.
- Default discovery must not execute discovered programs or make network calls.
- Treat paths, frontmatter, manifests, MCP files, CLI names, and probe output as untrusted.
- Do not embed specific third-party tool names as preferred routes.
- All public text passes through the sanitizer. Exact paths exist only in the private resolver.
- `setup plan` is zero-write. Mutating commands require `--confirmed`; setup also requires the exact plan hash.
- Every file mutation preserves unrelated content and is recoverable through a backup manifest.
- Tests use temporary homes, projects, PATH directories, and Vaults. Never install this Skill into the real machine during development.

## Task 1: Capability model and sanitizer

**Files:**

- Create: `skills/Agent能力/discover-local-capabilities/scripts/capability_map_core/__init__.py`
- Create: `skills/Agent能力/discover-local-capabilities/scripts/capability_map_core/models.py`
- Create: `skills/Agent能力/discover-local-capabilities/scripts/capability_map_core/sanitize.py`
- Create: `skills/Agent能力/discover-local-capabilities/tests/__init__.py`
- Create: `skills/Agent能力/discover-local-capabilities/tests/test_models_and_sanitize.py`

### RED

- Test a `Capability` with the complete public schema and conservative default states.
- Test deterministic opaque IDs and `resolver_id` values independent of usernames and absolute paths.
- Test serialization excludes private paths and unknown fields.
- Test sanitizer behavior for home paths, Unix and Windows absolute paths, `file://` paths, control characters, Markdown table breakers, newlines, oversized strings, and synthetic credentials.
- Construct credential canaries from fragments inside the test, for example `"gh" + "p_" + "synthetic"`, so repository safety hooks do not treat fixtures as live credentials.
- Verify redacted values do not survive in nested dict/list output.

Run and confirm failure:

```bash
python3 -m unittest skills.Agent能力.discover-local-capabilities.tests.test_models_and_sanitize -v
```

### GREEN

- Implement dataclasses for capability states, source locations, diagnostics, capabilities, and inventory metadata.
- Implement stable ID generation using normalized non-secret evidence.
- Implement recursive sanitization for strings and structured values.
- Keep public/private representations separate by API, not by caller discipline.

### REFACTOR AND VERIFY

- Remove duplicated schema construction.
- Keep serializers deterministic with sorted keys and stable list ordering.
- Re-run the focused test module and commit.

## Task 2: Root resolution and recursive Skill discovery

**Files:**

- Create: `skills/Agent能力/discover-local-capabilities/scripts/capability_map_core/roots.py`
- Create: `skills/Agent能力/discover-local-capabilities/scripts/capability_map_core/skills.py`
- Create: `skills/Agent能力/discover-local-capabilities/tests/support.py`
- Create: `skills/Agent能力/discover-local-capabilities/tests/test_skill_discovery.py`

### RED

- Build temporary Codex, Claude, shared-agent, project, plugin, and extra roots.
- Cover hidden `.system` Skills, arbitrary nesting, Unicode names, BOM, multiline frontmatter, invalid frontmatter, non-UTF-8 input, permission errors, broken links, symlink loops, and one physical Skill exposed through multiple logical paths.
- Assert physical deduplication retains all visible source locations, scopes, and providers.
- Assert discovery never escapes an allowed root through a symlink without a diagnostic.

Run and confirm failure:

```bash
python3 -m unittest skills.Agent能力.discover-local-capabilities.tests.test_skill_discovery -v
```

### GREEN

- Implement OS-aware and project-aware root providers with explicit dependency injection.
- Recursively locate `SKILL.md`, follow directory links safely, and track visited physical identities.
- Parse only the frontmatter fields needed for classification. Provide a conservative YAML subset parser with a documented fallback because production dependencies are forbidden.
- Record per-item diagnostics without aborting the full scan.

### REFACTOR AND VERIFY

- Separate traversal from metadata parsing.
- Ensure no production constant names a personal directory or project.
- Re-run Tasks 1 and 2 tests and commit.

## Task 3: Complete PATH CLI inventory

**Files:**

- Create: `skills/Agent能力/discover-local-capabilities/scripts/capability_map_core/clis.py`
- Create: `skills/Agent能力/discover-local-capabilities/tests/test_cli_discovery.py`

### RED

- Test Unix executable-bit handling, regular-file filtering, PATH order, duplicate directories, empty and relative entries, Unicode/space paths, and same-name shadow chains.
- Test simulated Windows `PATHEXT` and case-insensitive command matching without requiring Windows.
- Assert every executable appears in full inventory, only the first shadow entry is effective, and no fixed allowlist is used.
- Mock `subprocess.run` and assert default inventory never calls it.
- Test opt-in version probes use `shell=False`, `stdin=DEVNULL`, a minimal environment, a short timeout, output limits, and sanitizer coverage.

Run and confirm failure:

```bash
python3 -m unittest skills.Agent能力.discover-local-capabilities.tests.test_cli_discovery -v
```

### GREEN

- Enumerate all executable entries in each PATH directory.
- Normalize command names per OS while retaining each discovered source.
- Represent effective and shadowed entries explicitly.
- Add a separately invoked, disabled-by-default safe probe helper.

### REFACTOR AND VERIFY

- Keep filesystem enumeration and probing isolated.
- Re-run Tasks 1 through 3 tests and commit.

## Task 4: MCP and plugin adapters

**Files:**

- Create: `skills/Agent能力/discover-local-capabilities/scripts/capability_map_core/connectors.py`
- Create: `skills/Agent能力/discover-local-capabilities/tests/test_connectors.py`

### RED

- Test Codex TOML, Claude JSON, project `.mcp.json`, VS Code MCP JSON, and supported plugin-manifest declarations.
- Cover duplicate MCP names from multiple sources, disabled entries, damaged files, oversized configs, BOM, and malicious nested values.
- Assert public MCP entries contain only safe name/state/scope/provider/transport metadata and no command, args, URL, headers, env, token, or arbitrary values.
- Test nested `.codex-plugin/plugin.json` and `.claude-plugin/plugin.json` manifests, multiple versions, cache publisher directories, and malformed manifests.
- Assert publisher/cache directories without manifests are not plugins.

Run and confirm failure:

```bash
python3 -m unittest skills.Agent能力.discover-local-capabilities.tests.test_connectors -v
```

### GREEN

- Implement bounded config readers and source-specific adapters.
- Preserve same-name entities as distinct capabilities with separate source locations.
- Identify plugins from manifests only and return embedded Skill/MCP roots to the relevant collectors.

### REFACTOR AND VERIFY

- Centralize safe structured-file reading and diagnostics.
- Re-run discovery tests and commit.

## Task 5: Neutral classification, route queries, and public rendering

**Files:**

- Create: `skills/Agent能力/discover-local-capabilities/scripts/capability_map_core/classify.py`
- Create: `skills/Agent能力/discover-local-capabilities/scripts/capability_map_core/render.py`
- Create: `skills/Agent能力/discover-local-capabilities/references/scene-taxonomy.json`
- Create: `skills/Agent能力/discover-local-capabilities/tests/test_classify_and_render.py`
- Delete: `skills/Agent能力/discover-local-capabilities/references/routing-rules.json`

### RED

- Test classification from generic scene definitions plus local names, tags, descriptions, aliases, and manifest keywords.
- Test task-query token overlap and deterministic ranking.
- Assert specialized, evidenced capabilities outrank unclassified generic entries while low-confidence items remain in `待人工归类`.
- Assert removing any author-specific tools does not change the classifier's generic behavior.
- Test Markdown includes usage instructions, scene-to-capability routes, state boundaries, diagnostics, unresolved counts, refresh/migrate/uninstall help, and no exact resolver paths.
- Test inventory JSON contains every discovered item, including PATH shadow entries and unresolved items.
- DLP-scan Markdown and JSON output for all constructed canaries and source absolute paths.

Run and confirm failure:

```bash
python3 -m unittest skills.Agent能力.discover-local-capabilities.tests.test_classify_and_render -v
```

### GREEN

- Implement generic bilingual tokenization and evidence-weighted scene scoring.
- Keep taxonomy generic and free of preferred concrete tools.
- Implement route-query results with scores, evidence, state warnings, and resolver IDs.
- Render concise Markdown and complete deterministic JSON through the sanitizer.

### REFACTOR AND VERIFY

- Cap only presentation lists, never the inventory.
- Re-run Tasks 1 through 5 tests and commit.

## Task 6: Local/Obsidian storage and private resolver

**Files:**

- Create: `skills/Agent能力/discover-local-capabilities/scripts/capability_map_core/storage.py`
- Create: `skills/Agent能力/discover-local-capabilities/tests/test_storage.py`

### RED

- Test macOS, Linux XDG, and Windows default public/private data roots by injecting platform and environment values.
- Test explicit local paths and multiple Obsidian Vault candidates with Chinese, spaces, long names, iCloud-like, and network-like paths.
- Assert Vault detection reads only application configuration, never scans note contents.
- Assert public artifacts contain sanitized paths while exact paths exist only in the private resolver.
- Assert resolver mode is `0600` on Unix.
- Test staged atomic writes and cleanup after a simulated mid-write failure.

Run and confirm failure:

```bash
python3 -m unittest skills.Agent能力.discover-local-capabilities.tests.test_storage -v
```

### GREEN

- Implement public and private root policies with caller-selected overrides.
- Implement non-invasive Vault candidate discovery and explicit selection.
- Write map, inventory, config, receipt, and resolver through staging and atomic replacement.

### REFACTOR AND VERIFY

- Return a typed installation-path object used by later commands.
- Re-run storage and rendering tests and commit.

## Task 7: Managed Agent instructions and transactional recovery

**Files:**

- Create: `skills/Agent能力/discover-local-capabilities/scripts/capability_map_core/transactions.py`
- Create: `skills/Agent能力/discover-local-capabilities/scripts/capability_map_core/instructions.py`
- Create: `skills/Agent能力/discover-local-capabilities/tests/test_instructions.py`

### RED

- Test Codex user-level target resolution, including non-empty `AGENTS.override.md` shadowing `AGENTS.md`.
- Test Codex project `AGENTS.md`, Claude user `~/.claude/CLAUDE.md`, and Claude project `CLAUDE.md`.
- Test dry-run planning makes no writes.
- Test first install, idempotent reinstall, managed-block update, duplicate markers, damaged markers, unrelated user content, LF/CRLF, file mode preservation, and external modification between plan/apply.
- Simulate failure after one write and assert manifest-guided rollback restores exact bytes and metadata.
- Test uninstall removes only the matching managed block. Purging public/private data remains a separate explicit action.

Run and confirm failure:

```bash
python3 -m unittest skills.Agent能力.discover-local-capabilities.tests.test_instructions -v
```

### GREEN

- Implement deterministic plans and SHA-256 confirmation hashes.
- Implement stable managed-block rendering with installation ID and schema.
- Implement same-directory temporary writes, backups, atomic replace, manifests, rollback, and conservative conflict refusal.

### REFACTOR AND VERIFY

- Make the transaction engine generic across map artifacts and instruction files.
- Re-run Tasks 6 and 7 tests and commit.

## Task 8: Command workflow and compatibility entrypoint

**Files:**

- Create: `skills/Agent能力/discover-local-capabilities/scripts/capability_map.py`
- Replace: `skills/Agent能力/discover-local-capabilities/scripts/scan_capabilities.py`
- Create: `skills/Agent能力/discover-local-capabilities/tests/test_cli_workflow.py`

### RED

- Exercise `scan`, `setup plan`, `setup apply`, `status`, `paths`, `refresh`, `route`, `migrate`, and `uninstall` in an isolated temporary home/project.
- Assert `setup plan` writes nothing and prints deterministic JSON plus a plan hash.
- Assert apply rejects missing confirmation and stale hashes.
- Assert a complete install → route → refresh → migrate → uninstall loop works and leaves unrelated files untouched.
- Assert help-like natural-language queries map to usage, paths, refresh, migrate, and uninstall operations.
- Assert compatibility invocation maps old scan arguments to the new scan command.
- Mock subprocess and networking boundaries and assert default workflows make no discovered-command or network calls.

Run and confirm failure:

```bash
python3 -m unittest skills.Agent能力.discover-local-capabilities.tests.test_cli_workflow -v
```

### GREEN

- Wire collectors, classifier, renderer, storage, and transactions behind `argparse`.
- Support deterministic machine-readable stdout for Agent orchestration and concise human errors on stderr.
- Ensure every mutating branch has explicit confirmation and every receipt reports exact selected locations.

### REFACTOR AND VERIFY

- Keep command handlers thin and move policy into core modules.
- Run the entire unit suite and commit.

## Task 9: Skill instructions, usage docs, and repository index

**Files:**

- Replace: `skills/Agent能力/discover-local-capabilities/SKILL.md`
- Replace: `skills/Agent能力/discover-local-capabilities/README.md`
- Replace: `skills/Agent能力/discover-local-capabilities/agents/openai.yaml`
- Modify: `README.md`
- Delete if tracked: `skills/Agent能力/discover-local-capabilities/scripts/__pycache__/scan_capabilities.cpython-314.pyc`

### RED

- Add a documentation-consistency test or static assertions covering every public command, output artifact, confirmation rule, storage option, state warning, and natural-language help example.
- Assert package docs contain no author home path, machine snapshot, named preferred tool list, or legacy routing-rule reference.

### GREEN

- Make `SKILL.md` concise and action-oriented: discovery trigger, plan/apply confirmation, storage selection, Agent target selection, receipt, refresh, route, migration, uninstall, privacy guarantees, and troubleshooting.
- Explain in README that installing the Skill installs discovery logic only; it discovers the installer's capabilities and does not copy the author's tools or preferences.
- Update `agents/openai.yaml` prompts to prefer natural language and explicit confirmation.
- Correct root README counts/categories and list the Agent-capability Skill.

### VERIFY

- Run the full unit suite.
- Run Skill validation with the repository/environment-provided validator.
- Run a static docs-vs-parser command comparison and commit.

## Task 10: Release audit and GitHub replacement

**Files:**

- Modify only files required to fix verified release findings.

### VERIFY FROM A CLEAN STATE

1. Run all unit and integration tests with no ignored failures.
2. Run the Skill validator.
3. Run an isolated temporary-home lifecycle: setup plan, setup apply, route, refresh dry-run/apply, migrate dry-run/apply, uninstall.
4. DLP-scan every generated stdout, Markdown, JSON, config, receipt, resolver, and backup artifact for constructed synthetic canaries.
5. Confirm default execution makes zero discovered-program calls and zero network calls.
6. Search the Skill package for real home paths, generated maps, snapshots, author preferences, legacy allowlists, and secret-shaped literals.
7. Review `git diff`, `git status`, and commit history. Remove transient bytecode through a recoverable file move if needed.
8. Fetch origin and verify no unexpected divergence. Integrate safely without rewriting remote history.
9. Push the verified branch to replace `origin/main` only because the repository owner explicitly authorized this operation.
10. Re-fetch and verify the remote main commit and GitHub-visible files match the local release commit.

Expected final report:

- Release commit SHA and remote verification.
- Test and validation evidence.
- Public map/inventory and private resolver design summary.
- Confirmation/rollback guarantees.
- Explicit statement that no local capabilities or author preferences were shipped.

