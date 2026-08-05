#!/usr/bin/env node

import { main } from "../runtime/cli/taskctl.mjs";
import { ensureServer } from "./taskboard.mjs";

const server = await ensureServer();
process.env.CODEX_TASKBOARD_URL ||= server.origin;
process.exitCode = await main(process.argv.slice(2));
