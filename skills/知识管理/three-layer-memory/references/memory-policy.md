# Memory Policy

## Classification Order

Ask these questions in order:

1. Is it a secret, unconfirmed inference, noise, or expired state? Do not remember.
2. Is it a stable, confirmed fact that remains useful across tasks? Profile.
3. Is it a reusable action, rule, condition, or completion standard? Procedure.
4. Does it describe a specific event with a date, decision, result, or source? History.
5. If none apply, do not write it yet.

## Boundary Examples

| Input | Layer | Reason |
|---|---|---|
| 我长期偏好结论先行 | Profile | Confirmed cross-task preference |
| 写公众号前先搜索 Vault | Procedure | Reusable precondition |
| 2026-07-28 完成 Week2 Day1 | History | Dated event |
| 我今天不想看长文 | Do not remember by default | Temporary state |
| 我猜客户不喜欢长文 | Do not remember | Unconfirmed inference |
| 上次报价漏算税率 | History | Specific past event |
| 以后报价前必须核对税率 | Procedure | Reusable lesson extracted from history |
| API Key、密码、验证码 | Do not remember | Secret |

## Quality Rules

- Profile entries must be stable and confirmed.
- Procedure entries should contain an action and a usable condition or completion standard.
- History entries should contain a date and enough context to trace the event.
- Keep one canonical version of a rule. Do not copy procedures into every history log.
- Store the original event in history before promoting a repeated pattern into a procedure.
- Mark uncertain information as pending outside normal memory until confirmed.

## Loading Rules

- Start a task with profile and procedure memory.
- Load history only when the task needs past events.
- Prefer the smallest relevant context.
- Cite the source file when using memory.
- If memories conflict, prefer the newer confirmed entry and report the conflict.

