---
name: manage-taskboard
description: Manage taskboard projects, issues, issue relations, and comments through the taskctl CLI. Use when Codex needs to track a new requirement, inspect project work, create or update issues, relate dependent work, add progress notes, begin work on an issue, record completion, or coordinate concurrent updates.
---

# Manage Taskboard

Use `taskctl` for every project, issue, and comment operation. Read [references/cli.md](references/cli.md) before choosing a command or option.

## Workflow

1. Search for an existing issue before creating one. Use `context current`, then list the project issues and compare their identifiers, titles, descriptions, and status.
   - If an issue already tracks the same requirement, append the new requirement or acceptance detail to that issue without discarding its existing scope.
   - If the work depends on, blocks, is blocked by, or is closely related to another issue, add the matching issue relation.
   - Use a parent/sub-issue relation when one requirement is a contained part of a larger issue. A child has one parent; a parent may have many sub-issues.
   - Create a new issue only when no existing issue reasonably tracks the requirement.
   - Do not create, append, or relate a tiny or trivial request that does not benefit from durable tracking.
2. Before executing an issue, read the latest issue content and all comments. Treat comments as part of the current requirements, especially when completed work has been returned for changes.
   - In a description or comment, `![alt](/api/attachments/<id>/content)` marks an inline image at that exact position in the text.
   - When understanding that image is necessary, use `attachment download` to save it locally, then inspect the saved file with an available image-viewing tool.
3. Before implementation, honor the issue's execution metadata.
   - For a bound worktree, run commands and edit files only in its exact path.
   - For a bound branch, prefer an existing worktree checked out at that branch; otherwise verify the current workspace is already on the bound branch before editing. Never silently execute against a different branch. If the bound context cannot be used safely, add a comment with the exact unblock condition and move the issue to `blocked` with both `--blocked-reason` and `--unblock-action`.
   - Preserve `dueDate` during claims and handoffs. It affects automatic pickup order but does not override status, dependency, or review rules.
4. Create or update issues with the CLI; consume its JSON output.
   Issues created through `taskctl` are assigned to Codex Agent by default. Later CLI updates do not change the assignee.
5. Let `taskctl` attribute every issue, relation, or comment mutation to the current Codex conversation through `CODEX_THREAD_ID`. Outside Codex, pass the exact conversation id with `--thread-id`.
6. To claim a `todo` issue, move it to `in_progress` with `--if-version` from the latest read before starting implementation. If this claim reports a version conflict or a new read shows that its status changed, skip the issue and do not implement it.
7. Include `--if-version <version>` on every concurrent update, using the version returned by the latest read.
8. Before requesting review, verify the requested work and acceptance criteria.
9. An issue may remain `in_progress` only while Codex is actively working on it. Before a normal execution exits, choose the truthful outcome and add a comment explaining it:
   - Completed and self-verified: move to `in_review` after the result comment.
   - Temporarily interrupted but safe to retry without new external input: record the exact resume point and move back to `todo`.
   - Waiting for user input, missing information, or an unfinished dependency: move to `blocked` with `--blocked-reason` containing only the confirmed fact and `--unblock-action` containing one explicit action that will let work resume.
   - Never infer, summarize, or invent a blocking reason from status, comments, age, or incomplete context. Use explicit user input or a verified tool/runtime error as the source.
   - Never move to `canceled` unless the user explicitly decides the work should not continue.
   If a process terminates before cleanup, a later automation may recover the issue only after its `threadId` is confirmed failed or interrupted through Codex task/thread state. Never infer termination from age alone and never reset an active run.
10. After implementation and self-verification, add a comment summarizing the key changes, verification, result, and remaining risks; then move the issue to `in_review`. Never move it directly to `done`.
   - When the handoff prompt names a source comment, pass that comment id with `comment add --reply-to` so the result visibly links back to the feedback being addressed.
11. Move an issue from `in_review` to `done` only when the user explicitly confirms acceptance or explicitly asks to mark it complete. Codex self-verification alone is not sufficient.
12. Move work that cannot continue to `blocked`, always including the exact structured reason and unblock action. Move work that will not continue to `canceled`.

For version conflicts outside the initial claim, read the issue again, reconcile the newer state, and retry with its current version.
