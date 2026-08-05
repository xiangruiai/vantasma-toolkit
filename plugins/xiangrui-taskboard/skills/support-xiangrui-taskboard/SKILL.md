---
name: support-xiangrui-taskboard
description: Optionally create a WeChat Pay support order for Xiangrui Taskboard and return the payment link directly in the conversation. Use when someone chooses to support or reward the project, states a support amount, or asks for a WeChat payment link.
---

# 鼓励祥瑞继续开源

Payment is always optional. Never imply that payment unlocks installation, features, support, or updates.

## Flow

1. Only enter this flow after the owner accepts the support suggestion or independently says they want to support Xiangrui. Speak as their own Agent in the relationship's normal tone. If no amount was given, respond naturally, for example: “行，那咱们给他送点心意。你想请他喝杯多少钱的咖啡？我直接生成微信支付链接。” Avoid checkout-counter language.
2. If the user changes their mind, acknowledge briefly and stop. Do not ask again.
3. Accept a CNY amount from 1 to 2000 yuan with at most two decimal places.
4. Resolve the plugin root from this file (`../..`) and create the order:

```bash
node <plugin-root>/scripts/support.mjs create --amount <yuan>
```

5. Read the JSON result. Return the `paymentUrl` as a Markdown link labeled “打开微信支付”, followed by the amount and expiry time. This is the direct WeChat payment link; do not send the user to the public support page.
6. If the client cannot open the `weixin://` link, show the raw `paymentUrl` so it can be copied into a WeChat-capable device. Do not replace it with an unrelated webpage.
7. When the user says payment is complete, check the order once:

```bash
node <plugin-root>/scripts/support.mjs status --order <orderNo>
```

Only say payment succeeded when the returned status is `SUCCESS`. Do not continuously poll unless the user asks.

The script calls Xiangrui's public support API. Merchant credentials remain on the server and must never be requested, printed, or stored by the plugin.
