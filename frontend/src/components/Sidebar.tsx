import { useEffect, useState } from "react";
import { fetchConversations } from "../api";
import type { Conversation } from "../types";

interface Props {
  currentConvId: string | null;
  onNewChat: () => void;
}

export function Sidebar({ currentConvId, onNewChat }: Props) {
  const [convs, setConvs] = useState<Conversation[]>([]);

  useEffect(() => {
    fetchConversations()
      .then(setConvs)
      .catch(() => {/* silently ignore */});
  }, [currentConvId]);

  return (
    <div className="w-60 bg-gray-950 border-r border-gray-800 flex flex-col shrink-0">
      {/* Logo */}
      <div className="px-4 py-4 border-b border-gray-800">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-md bg-indigo-600 flex items-center justify-center text-xs font-bold">
            P
          </div>
          <span className="text-sm font-semibold text-gray-200">PAT</span>
        </div>
      </div>

      {/* New chat button */}
      <div className="px-3 py-2">
        <button
          onClick={onNewChat}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-gray-300 hover:bg-gray-800 transition-colors"
        >
          <span className="text-lg leading-none text-gray-500">+</span>
          New chat
        </button>
      </div>

      {/* Conversations */}
      <div className="flex-1 overflow-y-auto px-2 py-1">
        {convs.length === 0 ? (
          <p className="text-xs text-gray-600 px-3 py-2">No conversations yet</p>
        ) : (
          <div className="space-y-0.5">
            {convs.map((c) => (
              <ConvItem key={c.id} conv={c} active={c.id === currentConvId} />
            ))}
          </div>
        )}
      </div>

      {/* Footer links */}
      <div className="px-3 py-3 border-t border-gray-800 space-y-1">
        {[
          ["/schedules-ui", "⏰ Schedules"],
          ["/mcp-ui", "🔧 MCP Servers"],
        ].map(([href, label]) => (
          <a
            key={href}
            href={href}
            target="_blank"
            rel="noreferrer"
            className="block text-xs text-gray-500 hover:text-gray-300 transition-colors py-0.5 px-2 rounded hover:bg-gray-800"
          >
            {label}
          </a>
        ))}
      </div>
    </div>
  );
}

function ConvItem({ conv, active }: { conv: Conversation; active: boolean }) {
  const title =
    conv.title ||
    `Chat ${new Date(conv.created_at).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    })}`;

  return (
    <div
      className={`px-3 py-2 rounded-lg text-xs cursor-pointer transition-colors truncate ${
        active
          ? "bg-gray-800 text-gray-100"
          : "text-gray-400 hover:bg-gray-900 hover:text-gray-200"
      }`}
    >
      {title}
    </div>
  );
}
