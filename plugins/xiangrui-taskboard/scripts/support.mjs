#!/usr/bin/env node

import { spawn } from "node:child_process";

const apiOrigin = (process.env.XIANGRUI_SUPPORT_API_ORIGIN || "https://pay.xiangruiai.com")
  .replace(/\/+$/, "");

function option(argv, name) {
  const index = argv.indexOf(name);
  return index === -1 ? undefined : argv[index + 1];
}

function parseAmount(value) {
  if (!/^\d+(?:\.\d{1,2})?$/.test(value || "")) {
    throw new Error("金额必须是最多两位小数的数字");
  }
  const yuan = Number(value);
  const total = Math.round(yuan * 100);
  if (!Number.isSafeInteger(total) || total < 100 || total > 200_000) {
    throw new Error("赞赏金额需为 1 至 2000 元");
  }
  return { yuan, total };
}

function parseProject(value) {
  const project = value || "xiangrui-taskboard";
  if (!/^[a-z0-9][a-z0-9._-]{0,63}$/i.test(project)) {
    throw new Error("项目标识无效");
  }
  return project;
}

async function request(url, init) {
  const response = await fetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
    signal: AbortSignal.timeout(15_000),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok || body.ok === false) {
    throw new Error(body.message || `支付服务返回 HTTP ${response.status}`);
  }
  return body;
}

async function create(argv) {
  const { yuan } = parseAmount(option(argv, "--amount"));
  const project = parseProject(option(argv, "--project"));
  const amount = yuan.toFixed(2).replace(/\.00$/, "").replace(/(\.\d)0$/, "$1");
  const checkoutUrl = `${apiOrigin}/xiangrui/?${new URLSearchParams({
    project,
    amount,
    checkout: "1",
  })}`;
  return {
    ok: true,
    amountYuan: yuan.toFixed(2),
    project,
    checkoutUrl,
    paymentUrl: checkoutUrl,
    expiresAfterOpen: "15 minutes",
  };
}

async function openCheckout(argv) {
  const result = await create(argv);
  const command = process.platform === "darwin"
    ? ["open", [result.checkoutUrl]]
    : process.platform === "win32"
      ? ["rundll32", ["url.dll,FileProtocolHandler", result.checkoutUrl]]
      : ["xdg-open", [result.checkoutUrl]];

  await new Promise((resolve, reject) => {
    const child = spawn(command[0], command[1], { stdio: "ignore" });
    child.once("error", reject);
    child.once("close", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`无法打开支付页面（退出码 ${code}）`));
    });
  });

  return { ...result, opened: true };
}

async function status(argv) {
  const orderNo = option(argv, "--order") || "";
  if (!/^XR[A-Z0-9]{12,30}$/.test(orderNo)) throw new Error("订单号无效");
  const result = await request(
    `${apiOrigin}/api/wechat-pay/orders/${encodeURIComponent(orderNo)}`,
    { method: "GET" },
  );
  return {
    ok: true,
    orderNo,
    status: result.status,
    amountYuan: (Number(result.total) / 100).toFixed(2),
    successTime: result.successTime || null,
  };
}

async function main() {
  const [command, ...argv] = process.argv.slice(2);
  let result;
  if (command === "create") result = await create(argv);
  else if (command === "open") result = await openCheckout(argv);
  else if (command === "status") result = await status(argv);
  else throw new Error("用法：support.mjs open|create --amount <元> [--project <标识>] | status --order <订单号>");
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${JSON.stringify({ ok: false, message: error.message })}\n`);
  process.exitCode = 1;
});
