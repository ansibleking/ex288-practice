import { app, BrowserWindow, ipcMain } from "electron";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { mcpCallTool, mcpConnect, mcpDisconnect, mcpListTools } from "./mcpClient.js";
import { getApiKey, getSettings, setSettings } from "./settingsStore.js";
import { runChat } from "./anthropic.js";
import type { ChatContext, McpTool } from "./types.js";

const __dirname = dirname(fileURLToPath(import.meta.url));

const VITE_DEV_SERVER_URL = process.env.VITE_DEV_SERVER_URL;

function createWindow() {
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      preload: join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  if (VITE_DEV_SERVER_URL) {
    win.loadURL(VITE_DEV_SERVER_URL);
  } else {
    win.loadFile(join(__dirname, "../dist/index.html"));
  }
}

let cachedTools: McpTool[] = [];

ipcMain.handle("mcp:connect", async (_event, url: string) => {
  const result = await mcpConnect(url);
  if (result.ok) {
    setSettings({ serverUrl: url });
    try {
      cachedTools = await mcpListTools();
    } catch {
      cachedTools = [];
    }
  }
  return result;
});

ipcMain.handle("mcp:disconnect", async () => {
  cachedTools = [];
  await mcpDisconnect();
});

ipcMain.handle("mcp:listTools", async () => {
  cachedTools = await mcpListTools();
  return cachedTools;
});

ipcMain.handle("mcp:callTool", async (_event, name: string, args: Record<string, unknown>) => {
  return mcpCallTool(name, args ?? {});
});

ipcMain.handle("settings:get", async () => getSettings());

ipcMain.handle("settings:set", async (_event, input) => setSettings(input));

ipcMain.handle(
  "chat:send",
  async (_event, message: string, history: unknown[], context: ChatContext) => {
    const apiKey = getApiKey();
    if (!apiKey) {
      return { error: "No Anthropic API key set. Add one in Settings." };
    }
    const settings = getSettings();
    if (cachedTools.length === 0) {
      try {
        cachedTools = await mcpListTools();
      } catch (err) {
        return {
          error: `Not connected to an MCP server: ${err instanceof Error ? err.message : err}`,
        };
      }
    }
    try {
      return await runChat({
        apiKey,
        model: settings.model,
        tools: cachedTools,
        history: history ?? [],
        message,
        context: context ?? { activeEndpoint: null, endpoints: [] },
      });
    } catch (err) {
      return { error: err instanceof Error ? err.message : String(err) };
    }
  },
);

app.whenReady().then(() => {
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  void mcpDisconnect();
});
