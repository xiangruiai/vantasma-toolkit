---
name: three-layer-memory
description: Build and operate a safe three-layer personal memory system in an Obsidian or Markdown Vault. Use when the user asks to initialize memory, remember a stable profile or preference, preserve a reusable method, log a dated event, recall past work, test memory in a new conversation, or audit and consolidate profile, procedural, and historical memory.
---

# Three Layer Memory

Operate three memory layers:

- Profile: stable, confirmed facts answering “who are you?”
- Procedure: reusable, verified methods answering “how do you work?”
- History: dated, traceable events answering “what happened?”

Treat secrets, unconfirmed inferences, noise, and expired information as “do not remember”.

Read [references/memory-policy.md](references/memory-policy.md) when classification is ambiguous.

## Resolve the Vault

Use the current workspace root when it contains `.obsidian`. For a Markdown Vault without `.obsidian`, require `00.系统` plus at least one knowledge top-level directory such as `10.项目`, `20.领域`, `30.资源`, or `50.个人`.

An `AGENTS.md` file by itself is not a Vault marker. If the current workspace is not the Vault, stop and ask the user to open the exact Vault folder as the current project. Do not accept a broad directory such as `Documents` as the target.

## Initialize

Resolve `scripts/memory_system.py` relative to this skill directory.

1. Inspect the target paths without modifying them.
2. Run:

```bash
python3 <skill-dir>/scripts/memory_system.py init --vault "<vault>" --dry-run
```

3. Show the proposed files and rule changes.
4. After the user confirms, run the same command without `--dry-run`.
5. Run `audit` and read back the created files.

Initialization never overwrites existing files. It creates missing templates and adds a managed memory protocol to root `AGENTS.md`. It also makes `CLAUDE.md` reference `AGENTS.md` when needed.

## Remember

Classify before writing:

| Layer | Test | Target |
|---|---|---|
| Profile | Stable, confirmed, useful across tasks | `00.系统/agent/user.md` |
| Procedure | Reusable action, condition, or completion standard | `00.系统/agent/memory.md` |
| History | Dated event, decision, result, or pending item | `50.个人/对话日志/` |
| Do not remember | Secret, inference, noise, or expired state | No write |

For “记住：…” or “remember…”, show:

1. proposed layer;
2. reason;
3. target path;
4. normalized text;
5. confirmation or expiry status.

Do not write yet.

For “确认记住：…” or another explicit confirmation, run:

```bash
python3 <skill-dir>/scripts/memory_system.py append \
  --vault "<vault>" \
  --layer profile|procedure|history \
  --content "<normalized text>" \
  --source "<source>" \
  --confirmed
```

Reject passwords, API keys, access tokens, verification codes, private keys, and unconfirmed personal inferences.

## Recall

For “回忆…”, “找回…”, or “之前做过什么”:

```bash
python3 <skill-dir>/scripts/memory_system.py recall \
  --vault "<vault>" \
  --query "<query>"
```

Answer with the matched fact and its exact source path. Separate stable profile, reusable procedure, and dated history in the response.

If keyword recall returns nothing, say so. Do not invent a memory.

## Audit and Consolidate

For “整理记忆”, “记忆体检”, or “检查是否腐化”:

```bash
python3 <skill-dir>/scripts/memory_system.py audit --vault "<vault>"
```

Report missing files, missing loading rules, the Claude-to-AGENTS rule link, exact duplicates, and suspected secrets. Propose consolidation changes before editing.

Never delete memory automatically. Archive or rewrite only after explicit confirmation.

## New-Conversation Test

Pass only when a new conversation can:

1. state three confirmed profile facts;
2. follow one saved procedure;
3. retrieve one dated historical event;
4. cite the source layer and file;
5. avoid loading unrelated history.
