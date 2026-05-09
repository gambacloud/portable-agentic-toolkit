import { useEffect, useState } from "react";
import { fetchConversations } from "../api";
import type { Conversation } from "../types";

interface Props {
  currentConvId: string | null;
  onNewChat: () => void;
}

export function Sidebar({ currentConvId, onNewChat }: Props) {
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [activeTab, setActiveTab] = useState<"chats" | "reminders">("chats");
  const [reminders, setReminders] = useState<any[]>([]);

  useEffect(() => {
    fetchConversations()
      .then(setConvs)
      .catch(() => {/* silently ignore */});
  }, [currentConvId]);

  useEffect(() => {
    if (activeTab !== "reminders") return;
    const fetchReminders = async () => {
      try {
        const res = await fetch("/api/reminders");
        if (res.ok) {
          const data = await res.json();
          setReminders(data);
        }
      } catch (err) {}
    };
    fetchReminders();
    const interval = setInterval(fetchReminders, 30000);
    return () => clearInterval(interval);
  }, [activeTab]);

  return (
    <div className="w-60 bg-gray-950 border-r border-gray-800 flex flex-col shrink-0">
      {/* Logo */}
      <div className="px-4 py-4 border-b border-gray-800">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-rose-700 to-rose-900 shadow-sm shadow-rose-900/20 flex items-center justify-center text-xs font-brand font-black text-white ring-1 ring-white/10">
            GB
          </div>
          <div className="flex items-center text-base tracking-tight select-none cursor-default">
            <span className="font-brand font-black text-rose-700 tracking-wide">GAMBA</span>
            <span className="font-mono font-medium text-indigo-100 ml-0.5 opacity-90">BOT</span>
          </div>
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

      {/* Tabs */}
      <div className="flex px-3 pt-2 gap-1 border-b border-gray-800">
        <button
          onClick={() => setActiveTab("chats")}
          className={`flex-1 pb-2 text-xs font-medium border-b-2 transition-colors ${
            activeTab === "chats"
              ? "border-indigo-500 text-indigo-400"
              : "border-transparent text-gray-500 hover:text-gray-300"
          }`}
        >
          Chats
        </button>
        <button
          onClick={() => setActiveTab("reminders")}
          className={`flex-1 pb-2 text-xs font-medium border-b-2 transition-colors flex items-center justify-center gap-1.5 ${
            activeTab === "reminders"
              ? "border-indigo-500 text-indigo-400"
              : "border-transparent text-gray-500 hover:text-gray-300"
          }`}
        >
          Reminders {reminders.length > 0 && <span className="bg-indigo-600 text-white rounded-full px-1.5 py-0.5 text-[9px] leading-none">{reminders.length}</span>}
        </button>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto px-2 py-1">
        {activeTab === "chats" ? (
          convs.length === 0 ? (
            <p className="text-xs text-gray-600 px-3 py-2">No conversations yet</p>
          ) : (
            <div className="space-y-0.5 mt-1">
              {convs.map((c) => (
                <ConvItem key={c.id} conv={c} active={c.id === currentConvId} />
              ))}
            </div>
          )
        ) : (
          reminders.length === 0 ? (
            <p className="text-xs text-gray-600 px-3 py-2">No pending reminders</p>
          ) : (
            <div className="space-y-1.5 mt-1 px-1">
              {reminders.map((r) => (
                <ReminderItem key={r.id} reminder={r} onDismiss={(id) => setReminders((prev) => prev.filter((x) => x.id !== id))} />
              ))}
            </div>
          )
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

function ReminderItem({ reminder, onDismiss }: { reminder: any; onDismiss: (id: string) => void }) {
  const remindDate = new Date(reminder.remind_at);
  const now = new Date();
  const isToday = remindDate.toDateString() === now.toDateString();
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  const isTomorrow = remindDate.toDateString() === tomorrow.toDateString();
  const timeStr = remindDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const dateLabel = isToday ? `Today ${timeStr}` : isTomorrow ? `Tomorrow ${timeStr}` : `${remindDate.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${timeStr}`;

  const dismiss = async (e: React.MouseEvent) => {
    e.stopPropagation();
    await fetch(`/api/reminders/${reminder.id}/complete`, { method: 'PUT' });
    onDismiss(reminder.id);
  };

  return (
    <div className="px-3 py-2 rounded-lg text-xs bg-gray-900 border border-gray-800 hover:border-indigo-500 hover:bg-gray-800 transition-all text-gray-300 group">
      <div className="flex items-center justify-between mb-1">
        <span className="font-semibold text-indigo-400">🕒 {dateLabel}</span>
        <button
          onClick={dismiss}
          className="text-gray-600 hover:text-red-400 transition-colors text-[10px] opacity-0 group-hover:opacity-100"
          title="Dismiss"
        >
          ✕
        </button>
      </div>
      <div className="text-gray-500 truncate group-hover:text-gray-300 transition-colors" title={reminder.session_id}>
        Chat: {reminder.session_id?.slice(0, 8) || "..."}
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
      onClick={() => { if (!active) window.location.href = `/?conv=${conv.id}`; }}
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
