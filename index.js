/**
 * DataCheck MCP Server — npm 入口
 *
 * 这个文件是 npm 包的 wrapper：
 *   · 用 npx @pixharvest/datacheck-mcp 启动时，它会调用 Python
 *   · 如果系统没有 Python，提示用户
 *
 * 为什么用 Python 而不是纯 JS？
 *   校验逻辑已经用 Python 写好了并有 36 项测试，
 *   重写一份 JS 版会有不一致风险。
 */
"use strict";

const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");

const SERVER_PY = path.join(__dirname, "server.py");

function findPython() {
  const candidates = [
    process.env.DATACHECK_PYTHON,
    "python3",
    "python",
    process.platform === "win32" ? "py" : null,
  ].filter(Boolean);

  for (const cmd of candidates) {
    try {
      const { execSync } = require("child_process");
      execSync(`"${cmd}" --version`, { stdio: "ignore", timeout: 5000 });
      return cmd;
    } catch {
      continue;
    }
  }
  return null;
}

function main() {
  if (!fs.existsSync(SERVER_PY)) {
    process.stderr.write(
      `[datacheck-mcp] server.py not found at ${SERVER_PY}\n` +
        `This package may be installed incorrectly.\n`
    );
    process.exit(1);
  }

  const python = findPython();
  if (!python) {
    process.stderr.write(
      "[datacheck-mcp] Python 3 is required but was not found.\n" +
        "Install Python 3.9+ and try again, or set DATACHECK_PYTHON to its path.\n"
    );
    process.exit(1);
  }

  const child = spawn(python, [SERVER_PY], {
    stdio: ["inherit", "inherit", "inherit"],
  });

  child.on("exit", (code) => process.exit(code ?? 0));
  child.on("error", (err) => {
    process.stderr.write(`[datacheck-mcp] failed to start: ${err.message}\n`);
    process.exit(1);
  });

  // 转发终止信号
  for (const sig of ["SIGINT", "SIGTERM"]) {
    process.on(sig, () => child.kill(sig));
  }
}

main();
