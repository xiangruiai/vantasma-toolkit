#!/usr/bin/env node

const apiOrigin = (process.env.XIANGRUI_SUPPORT_API_ORIGIN || "https://support.xiangruiai.com")
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
  const { yuan, total } = parseAmount(option(argv, "--amount"));
  const project = parseProject(option(argv, "--project"));
  const result = await request(`${apiOrigin}/api/wechat-pay/orders`, {
    method: "POST",
    body: JSON.stringify({ total, project }),
  });
  if (!result.codeUrl || !result.outTradeNo || !result.expiresAt) {
    throw new Error("支付服务返回的订单信息不完整");
  }
  return {
    ok: true,
    amountYuan: yuan.toFixed(2),
    project,
    orderNo: result.outTradeNo,
    paymentUrl: result.codeUrl,
    expiresAt: result.expiresAt,
  };
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
  else if (command === "status") result = await status(argv);
  else throw new Error("用法：support.mjs create --amount <元> [--project <标识>] | status --order <订单号>");
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

main().catch((error) => {
  process.stderr.write(`${JSON.stringify({ ok: false, message: error.message })}\n`);
  process.exitCode = 1;
});
