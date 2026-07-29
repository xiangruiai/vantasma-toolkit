import { test } from "node:test";
import assert from "node:assert/strict";
import { setLanguage, getLanguage, t } from "../dist/i18n/index.js";
import { mergeConfig } from "../dist/config.js";

test("t() returns English strings by default", () => {
  setLanguage("en");
  assert.equal(t("label.context"), "Context");
  assert.equal(t("label.usage"), "Usage");
  assert.equal(t("label.approxRam"), "Approx RAM");
  assert.equal(t("status.limitReached"), "Limit reached");
  assert.equal(t("status.allTodosComplete"), "All todos complete");
});

test("t() returns Chinese strings when language is zh", () => {
  setLanguage("zh");
  assert.equal(t("label.context"), "上下文");
  assert.equal(t("label.usage"), "用量");
  assert.equal(t("label.approxRam"), "内存");
  assert.equal(t("label.rules"), "规则");
  assert.equal(t("label.hooks"), "钩子");
  assert.equal(t("status.limitReached"), "已达上限");
  assert.equal(t("status.allTodosComplete"), "全部完成");
  assert.equal(t("format.in"), "输入");
  assert.equal(t("format.cache"), "缓存");
  assert.equal(t("format.out"), "输出");
  // Restore
  setLanguage("en");
});

test("setLanguage and getLanguage round-trip", () => {
  setLanguage("zh");
  assert.equal(getLanguage(), "zh");
  setLanguage("en");
  assert.equal(getLanguage(), "en");
});

test("mergeConfig defaults to English when no language is specified", () => {
  const config = mergeConfig({});
  assert.equal(config.language, "en");
});

test("mergeConfig preserves explicit language from config", () => {
  const config = mergeConfig({ language: "zh" });
  assert.equal(config.language, "zh");

  const config2 = mergeConfig({ language: "en" });
  assert.equal(config2.language, "en");
});

test("mergeConfig falls back to English for invalid language", () => {
  const config = mergeConfig({ language: "invalid" });
  assert.equal(config.language, "en");
});
