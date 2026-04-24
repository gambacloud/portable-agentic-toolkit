import { useCallback, useEffect, useRef, useState } from "react";
import { buildWsUrl } from "../api";
import type {
  ChatMessage,
  ChatSettings,
  HitlRequest,
  Profile,
  ReadyPayload,
  ServerMessage,
} from "../types";

let _msgSeq = 0;
const mkId = () => `m${++_msgSeq}`;

interface UseChatReturn {
  messages: ChatMessage[];
  hitl: HitlRequest | null;
  isThinking: boolean;
  isConnected: boolean;
  convId: string | null;
  shortId: string | null;
  models: string[];
  profiles: Profile[];
  mcpServers: string[];
  settings: ChatSettings;
  updateSettings: (patch: Partial<ChatSettings>) => void;
  sendMessage: (content: string) => void;
  sendHitlResponse: (id: string, value: string) => void;
  clearMessages: () => void;
}

export function useChat(userId = "local"): UseChatReturn {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const settingsRef = useRef<ChatSettings>({
    model: "llama3.2",
    profileId: null,
    verbose: true,
    multiAgent: false,
    activeMcps: [],
  });

  const [isConnected, setIsConnected] = useState(false);
  const [isThinking, setIsThinking] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [hitl, setHitl] = useState<HitlRequest | null>(null);
  const [convId, setConvId] = useState<string | null>(null);
  const [shortId, setShortId] = useState<string | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [mcpServers, setMcpServers] = useState<string[]>([]);
  const [settings, setSettings] = useState<ChatSettings>(settingsRef.current);

  const addMessage = useCallback((msg: Omit<ChatMessage, "id" | "ts">) => {
    setMessages((prev) => [...prev, { ...msg, id: mkId(), ts: Date.now() }]);
  }, []);

  const send = useCallback((data: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
    }

    const ws = new WebSocket(buildWsUrl(userId));
    wsRef.current = ws;

    ws.onopen = () => {
      setIsConnected(true);
    };

    ws.onmessage = (ev) => {
      let msg: ServerMessage;
      try {
        msg = JSON.parse(ev.data as string) as ServerMessage;
      } catch {
        return;
      }

      switch (msg.type) {
        case "ready": {
          const p = msg as unknown as ReadyPayload & { type: "ready" };
          setConvId(p.conv_id);
          setShortId(p.short_id);
          setModels(p.models);
          setProfiles(p.profiles);
          setMcpServers(p.mcp_servers);

          const newSettings: ChatSettings = {
            model: p.model,
            profileId: null,
            verbose: true,
            multiAgent: false,
            activeMcps: p.active_mcps,
          };
          settingsRef.current = newSettings;
          setSettings(newSettings);

          // Inject scheduler notifications as system messages
          for (const n of p.notifications) {
            addMessage({
              role: "system",
              content: `📅 **Scheduled task completed:** ${n.schedule_name}\n\n_Ran at: ${n.ran_at} UTC_\n\n${n.result}`,
            });
          }
          break;
        }

        case "step":
          addMessage({ role: "step", content: msg.content, stepName: msg.name });
          break;

        case "response":
          setIsThinking(false);
          setHitl(null);
          addMessage({ role: "assistant", content: msg.content });
          break;

        case "draft":
          addMessage({
            role: "draft",
            content: msg.content,
            draftTitle: msg.title,
            draftLanguage: msg.language,
          });
          break;

        case "hitl_request":
          setHitl({ id: msg.id, prompt: msg.prompt, choices: msg.choices });
          break;

        case "error":
          setIsThinking(false);
          setHitl(null);
          addMessage({ role: "error", content: msg.content });
          break;
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
      setIsThinking(false);
      // Reconnect after 3s
      reconnectTimer.current = setTimeout(() => connect(), 3000);
    };

    ws.onerror = () => ws.close();
  }, [userId, addMessage]);

  useEffect(() => {
    connect();
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
      }
    };
  }, [connect]);

  const sendMessage = useCallback(
    (content: string) => {
      if (!content.trim() || !isConnected || isThinking) return;
      addMessage({ role: "user", content });
      setIsThinking(true);
      send({ type: "message", content });
    },
    [isConnected, isThinking, addMessage, send]
  );

  const sendHitlResponse = useCallback(
    (id: string, value: string) => {
      setHitl(null);
      send({ type: "hitl_response", id, value });
    },
    [send]
  );

  const updateSettings = useCallback(
    (patch: Partial<ChatSettings>) => {
      const next = { ...settingsRef.current, ...patch };
      settingsRef.current = next;
      setSettings(next);
      send({
        type: "settings",
        model: next.model,
        profile_id: next.profileId,
        verbose: next.verbose,
        multi_agent: next.multiAgent,
        active_mcps: next.activeMcps,
      });
    },
    [send]
  );

  const clearMessages = useCallback(() => setMessages([]), []);

  return {
    messages,
    hitl,
    isThinking,
    isConnected,
    convId,
    shortId,
    models,
    profiles,
    mcpServers,
    settings,
    updateSettings,
    sendMessage,
    sendHitlResponse,
    clearMessages,
  };
}
