import { contextBridge, ipcRenderer } from "electron";
import type { RedfishApi } from "./types.js";

const api: RedfishApi = {
  mcp: {
    connect: (url) => ipcRenderer.invoke("mcp:connect", url),
    disconnect: () => ipcRenderer.invoke("mcp:disconnect"),
    listTools: () => ipcRenderer.invoke("mcp:listTools"),
    callTool: (name, args) => ipcRenderer.invoke("mcp:callTool", name, args),
  },
  settings: {
    get: () => ipcRenderer.invoke("settings:get"),
    set: (input) => ipcRenderer.invoke("settings:set", input),
  },
  chat: {
    send: (message, anthropicHistory, context) =>
      ipcRenderer.invoke("chat:send", message, anthropicHistory, context),
  },
};

contextBridge.exposeInMainWorld("api", api);
