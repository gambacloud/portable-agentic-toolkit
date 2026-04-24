import type { Conversation } from "./types";

const BASE = "";  // same origin in prod; proxied in dev

async function get<T>(path: string, userId = "local"): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "X-User-ID": userId },
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const fetchConversations = (userId = "local") =>
  get<Conversation[]>("/users/me/conversations", userId);

export function buildWsUrl(userId = "local"): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  // In dev (port 5173) the vite proxy rewrites /ws → localhost:8002/ws
  // In prod (port 8002) it's the same origin
  const host = window.location.host;
  return `${proto}://${host}/ws/chat?user_id=${encodeURIComponent(userId)}`;
}
