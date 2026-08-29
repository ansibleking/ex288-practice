import { app, safeStorage } from "electron";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { Settings, SettingsInput } from "./types.js";

interface StoredFile {
  serverUrl: string;
  model: string;
  encryptedApiKey: string | null; // base64
}

const DEFAULTS: StoredFile = {
  serverUrl: "http://127.0.0.1:8787/mcp",
  model: "claude-sonnet-5",
  encryptedApiKey: null,
};

function filePath(): string {
  return join(app.getPath("userData"), "settings.json");
}

function readFile(): StoredFile {
  const path = filePath();
  if (!existsSync(path)) return { ...DEFAULTS };
  try {
    const raw = JSON.parse(readFileSync(path, "utf-8"));
    return { ...DEFAULTS, ...raw };
  } catch {
    return { ...DEFAULTS };
  }
}

function writeFile(data: StoredFile): void {
  writeFileSync(filePath(), JSON.stringify(data, null, 2), "utf-8");
}

export function getSettings(): Settings {
  const stored = readFile();
  return {
    serverUrl: stored.serverUrl,
    model: stored.model,
    hasApiKey: Boolean(stored.encryptedApiKey),
  };
}

export function getApiKey(): string | null {
  const stored = readFile();
  if (!stored.encryptedApiKey) return null;
  if (!safeStorage.isEncryptionAvailable()) return null;
  try {
    return safeStorage.decryptString(Buffer.from(stored.encryptedApiKey, "base64"));
  } catch {
    return null;
  }
}

export function setSettings(input: SettingsInput): Settings {
  const stored = readFile();
  if (input.serverUrl !== undefined) stored.serverUrl = input.serverUrl;
  if (input.model !== undefined) stored.model = input.model;
  if (input.apiKey !== undefined) {
    if (input.apiKey === null || input.apiKey === "") {
      stored.encryptedApiKey = null;
    } else if (safeStorage.isEncryptionAvailable()) {
      stored.encryptedApiKey = safeStorage.encryptString(input.apiKey).toString("base64");
    } else {
      throw new Error("OS-level credential encryption is unavailable on this machine.");
    }
  }
  writeFile(stored);
  return getSettings();
}
