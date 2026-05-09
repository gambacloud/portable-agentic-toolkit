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

export function buildWsUrl(userId = "local", convId?: string): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const host = window.location.host;
  let url = `${proto}://${host}/ws/chat?user_id=${encodeURIComponent(userId)}`;
  if (convId) url += `&resume_conv_id=${encodeURIComponent(convId)}`;
  return url;
}
