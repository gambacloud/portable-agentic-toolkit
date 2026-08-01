import { useEffect, useState } from "react";
import { cleanupEmptyConversations, deleteConversation, fetchConversations } from "../api";
import type { Conversation } from "../types";

interface Props {
  currentConvId: string | null;
  onNewChat: () => void;
}

export function Sidebar({ currentConvId, onNewChat }: Props) {
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [activeTab, setActiveTab] = useState<"chats" | "reminders">("chats");
  const [reminders, setReminders] = useState<any[]>([]);
  const [cleaning, setCleaning] = useState(false);
  const [startingNewChat, setStartingNewChat] = useState(false);

  const handleNewChatClick = () => {
    // Navigating away can take a few seconds (WS reconnect + MCP discovery) —
    // give instant feedback so a click doesn't look like it did nothing.
    // The setTimeout lets the browser actually paint that state before the
    // navigation (triggered inside onNewChat) starts tearing the page down.
    setStartingNewChat(true);
    setTimeout(onNewChat, 0);
  };

  useEffect(() => {
    fetchConversations()
      .then(setConvs)
      .catch(() => {/* silently ignore */});
  }, [currentConvId]);

  const handleDeleteConv = async (id: string) => {
    try {
      await deleteConversation(id);
      setConvs((prev) => prev.filter((c) => c.id !== id));
      if (id === currentConvId) window.location.href = "/";
    } catch {
      /* silently ignore */
    }
  };

  const handleClearEmpty = async () => {
    setCleaning(true);
    try {
      await cleanupEmptyConversations();
      fetchConversations().then(setConvs).catch(() => {});
    } catch {
      /* silently ignore */
    } finally {
      setCleaning(false);
    }
  };

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
          onClick={handleNewChatClick}
          disabled={startingNewChat}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sm text-gray-300 hover:bg-gray-800 transition-colors disabled:opacity-60 disabled:cursor-wait"
        >
          {startingNewChat ? (
            <span className="w-3.5 h-3.5 rounded-full border-2 border-gray-600 border-t-gray-300 animate-spin shrink-0" />
          ) : (
            <span className="text-lg leading-none text-gray-500">+</span>
          )}
          {startingNewChat ? "Starting new chat…" : "New chat"}
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
            <div className="mt-1">
              <div className="flex justify-end px-1 pb-1">
                <button
                  onClick={handleClearEmpty}
                  disabled={cleaning}
                  className="text-[10px] text-gray-600 hover:text-gray-300 transition-colors disabled:opacity-50"
                >
                  {cleaning ? "Clearing…" : "Clear empty chats"}
                </button>
              </div>
              <div className="space-y-0.5">
                {convs.map((c) => (
                  <ConvItem key={c.id} conv={c} active={c.id === currentConvId} onDelete={handleDeleteConv} />
                ))}
              </div>
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

function ConvItem({
  conv,
  active,
  onDelete,
}: {
  conv: Conversation;
  active: boolean;
  onDelete: (id: string) => void;
}) {
  const [switching, setSwitching] = useState(false);

  const title =
    conv.title ||
    `Chat ${new Date(conv.created_at).toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    })}`;

  const del = (e: React.MouseEvent) => {
    e.stopPropagation();
    onDelete(conv.id);
  };

  const open = () => {
    if (active || switching) return;
    // Switching conversations does a full navigation (WS reconnect + MCP
    // discovery, a few seconds) — show instant feedback so it's clear the
    // click registered instead of looking like nothing happened. The
    // setTimeout lets the browser paint that state before navigating away.
    setSwitching(true);
    setTimeout(() => { window.location.href = `/?conv=${conv.id}`; }, 0);
  };

  return (
    <div
      onClick={open}
      className={`group flex items-center justify-between gap-1 px-3 py-2 rounded-lg text-xs transition-colors ${
        switching ? "cursor-wait opacity-60" : "cursor-pointer"
      } ${
        active
          ? "bg-gray-800 text-gray-100"
          : "text-gray-400 hover:bg-gray-900 hover:text-gray-200"
      }`}
    >
      <span className="flex items-center gap-1.5 min-w-0">
        {switching && (
          <span className="w-2.5 h-2.5 rounded-full border-2 border-gray-600 border-t-gray-300 animate-spin shrink-0" />
        )}
        <span className="truncate">{title}</span>
      </span>
      <button
        onClick={del}
        className="text-gray-600 hover:text-red-400 transition-colors text-[10px] opacity-0 group-hover:opacity-100 shrink-0"
        title="Delete chat"
      >
        ✕
      </button>
    </div>
  );
}
