export type MessageRole = "user" | "assistant" | "step" | "draft" | "error" | "system";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  // step-specific
  stepName?: string;
  // draft-specific
  draftTitle?: string;
  draftLanguage?: string;
  // timestamp
  ts: number;
}

export interface HitlRequest {
  id: string;
  prompt: string;
  choices: string[];
}

export interface Profile {
  id: string;
  name: string;
}

export interface ChatSettings {
  model: string;
  profileId: string | null;
  verbose: boolean;
  multiAgent: boolean;
  activeMcps: string[];
}

export interface ReadyPayload {
  conv_id: string | null;
  short_id: string | null;
  models: string[];
  profiles: Profile[];
  mcp_servers: string[];
  active_mcps: string[];
  model: string;
  notifications: Array<{
    schedule_name: string;
    ran_at: string;
    result: string;
  }>;
}

export interface Conversation {
  id: string;
  short_id: string | null;
  title: string | null;
  model: string;
  created_at: string;
}

// WebSocket message types (server → client)
export type ServerMessage =
  | { type: "ready" } & ReadyPayload
  | { type: "step"; name: string; content: string }
  | { type: "response"; content: string }
  | { type: "draft"; title: string; content: string; language: string }
  | { type: "hitl_request"; id: string; prompt: string; choices: string[] }
  | { type: "error"; content: string };

// WebSocket message types (client → server)
export type ClientMessage =
  | { type: "message"; content: string }
  | { type: "hitl_response"; id: string; value: string }
  | { type: "settings" } & Partial<{
      model: string;
      profile_id: string | null;
      verbose: boolean;
      multi_agent: boolean;
      active_mcps: string[];
    }>;
