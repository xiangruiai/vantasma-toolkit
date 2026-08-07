import assert from "node:assert/strict";
import { test } from "node:test";

let projectIdentity;
try {
  projectIdentity = await import("../web/src/projectIdentity.mjs");
} catch {
  projectIdentity = null;
}

test("project identity resolver is available to the taskboard UI", () => {
  assert.equal(typeof projectIdentity?.createProjectIdentityResolver, "function");
});

test("a Codex project opens the existing board for the same workspace", () => {
  const workspacePath = "/Users/xiangrui/Projects/dashi-taskboard";
  const resolver = projectIdentity.createProjectIdentityResolver({
    persistedProjects: [
      {
        id: "dashi-taskboard",
        name: "xiangrui",
        workspacePath,
        issueCount: 15,
        createdAt: "2026-08-05T00:00:00.000Z",
      },
      {
        id: "codex-generated-id",
        name: "dashi-taskboard",
        workspacePath: null,
        issueCount: 0,
        createdAt: "2026-08-05T01:00:00.000Z",
      },
    ],
    codexProjects: [{ id: "codex-generated-id", name: "dashi-taskboard" }],
    workspacePaths: {
      "codex-generated-id": `${workspacePath}/`,
    },
  });

  assert.equal(resolver?.canonicalProjectId?.("codex-generated-id"), "dashi-taskboard");
  assert.equal(resolver?.canonicalProjectId?.("dashi-taskboard"), "dashi-taskboard");
  assert.equal(resolver?.isCanonicalPersistedProject?.("dashi-taskboard"), true);
  assert.equal(resolver?.isCanonicalPersistedProject?.("codex-generated-id"), false);
  assert.equal(resolver?.hasCodexProject?.("dashi-taskboard"), true);
  assert.equal(resolver?.workspacePathFor?.("dashi-taskboard"), workspacePath);
});

test("projects with the same name but different workspaces stay separate", () => {
  const resolver = projectIdentity.createProjectIdentityResolver({
    persistedProjects: [
      {
        id: "first",
        name: "website",
        workspacePath: "/work/first",
        issueCount: 3,
        createdAt: "2026-08-05T00:00:00.000Z",
      },
      {
        id: "second",
        name: "website",
        workspacePath: "/work/second",
        issueCount: 0,
        createdAt: "2026-08-05T01:00:00.000Z",
      },
    ],
    codexProjects: [],
    workspacePaths: {},
  });

  assert.equal(resolver?.canonicalProjectId?.("first"), "first");
  assert.equal(resolver?.canonicalProjectId?.("second"), "second");
  assert.equal(resolver?.isCanonicalPersistedProject?.("first"), true);
  assert.equal(resolver?.isCanonicalPersistedProject?.("second"), true);
});
