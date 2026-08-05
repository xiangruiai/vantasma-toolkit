---
name: support-xiangrui-taskboard
description: Optionally open Xiangrui Taskboard's WeChat Pay checkout page with the chosen amount. Use when someone chooses to support or reward the project, states a support amount, or asks for WeChat payment.
---

# 鼓励祥瑞继续开源

Payment is always optional. Never imply that payment unlocks installation, features, support, or updates.

## Flow

1. Only enter this flow after the owner accepts the support suggestion or independently says they want to support Xiangrui. Speak as their own Agent in the relationship's normal tone. If no amount was given, respond naturally, for example: “行，那咱们给他送点心意。你想请他喝杯多少钱的咖啡？你说个金额，我直接帮你打开微信支付页面。” Avoid checkout-counter language.
2. If the user changes their mind, acknowledge briefly and stop. Do not ask again.
3. Accept a CNY amount from 1 to 2000 yuan with at most two decimal places.
4. Resolve the plugin root from this file (`../..`) and open the checkout page directly:

```bash
node <plugin-root>/scripts/support.mjs open --amount <yuan>
```

5. Read the JSON result. When `opened` is true, tell the user briefly that the page has opened with the selected amount. The page loads Xiangrui's support card, automatically creates the order, and directly displays the QR code. Its 15-minute validity starts when the page opens.
6. Do not return a `weixin://` URL and do not make the user ask for or click another link. If the open command genuinely fails, run the same script with `create` instead and return `checkoutUrl` once as the fallback clickable page.
7. Payment status updates automatically on the checkout page. Do not ask the user to return to the conversation for manual verification, and do not claim payment succeeded unless the page reports success.

Merchant credentials remain on Xiangrui's server and must never be requested, printed, or stored by the plugin.
