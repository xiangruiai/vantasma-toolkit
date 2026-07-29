import { test } from 'node:test';
import assert from 'node:assert/strict';
import { render } from '../dist/render/index.js';

function stripAnsi(str) {
  // eslint-disable-next-line no-control-regex
  return str
    .replace(/\x1b\[[0-9;]*m/g, '')
    .replace(/\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)/g, '');
}

function baseCtx(brand) {
  return {
    stdin: {
      model: { display_name: 'Opus 4.8 (1M context)' },
      cwd: '/tmp/demo',
      context_window: {
        context_window_size: 200000,
        current_usage: { input_tokens: 10000, cache_creation_input_tokens: 0, cache_read_input_tokens: 0 },
      },
    },
    transcript: { tools: [], agents: [], todos: [] },
    claudeMdCount: 0,
    rulesCount: 0,
    mcpCount: 0,
    hooksCount: 0,
    sessionDuration: '',
    gitStatus: null,
    usageData: null,
    config: {
      lineLayout: 'compact',
      showSeparators: false,
      pathLevels: 1,
      gitStatus: { enabled: true, showDirty: true, showAheadBehind: false, showFileStats: false },
      display: { showModel: true, showContextBar: true, contextValue: 'percent', autocompactBuffer: 'enabled', brand },
    },
    extraLabel: null,
  };
}

function captureRaw(ctx) {
  const logs = [];
  const originalLog = console.log;
  console.log = line => logs.push(line);
  try {
    render(ctx);
  } finally {
    console.log = originalLog;
  }
  return logs;
}

test('brand on: 首行带翠绿 ❖ 前缀，末行带 xiangrui-hud wordmark', () => {
  const raw = captureRaw(baseCtx(true));
  const plain = raw.map(stripAnsi);
  assert.ok(plain.length > 0, '应有输出');
  assert.ok(plain[0].startsWith('❖ '), `首行应以 ❖ 开头，实际: ${plain[0]}`);
  assert.ok(plain[plain.length - 1].includes('xiangrui-hud'), '末行应含 xiangrui-hud wordmark');
  // ❖ 应被翠绿 truecolor 包裹
  assert.ok(raw[0].includes('\x1b[38;2;34;166;103m❖'), '❖ 应为品牌翠绿 #22a667');
});

test('brand off: 无 ❖ 前缀，无 wordmark', () => {
  const plain = captureRaw(baseCtx(false)).map(stripAnsi);
  assert.ok(!plain[0].startsWith('❖'), '首行不应带 ❖');
  assert.ok(!plain.some(line => line.includes('xiangrui-hud')), '不应出现 wordmark');
});

test('brand 默认开启（display.brand 缺省时视为 true）', () => {
  const ctx = baseCtx(true);
  delete ctx.config.display.brand;
  const plain = captureRaw(ctx).map(stripAnsi);
  assert.ok(plain[0].startsWith('❖ '), '缺省应默认显示品牌');
});
