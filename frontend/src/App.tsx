import { useEffect, useRef, useState } from "react";
import { Toaster } from "react-hot-toast";
import { HitlButtons } from "./components/HitlButtons";
import { InputBar } from "./components/InputBar";
import { Message } from "./components/Message";
import { SettingsDrawer } from "./components/SettingsDrawer";
import { Sidebar } from "./components/Sidebar";
import { useChat } from "./hooks/useChat";
import { useReminderNotifications } from "./hooks/useReminderNotifications";

const USER_ID = "local";

export default function App() {
  const {
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
    stopGeneration,
  } = useChat(USER_ID);

  useReminderNotifications();

  const [settingsOpen, setSettingsOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, hitl, isThinking]);

  const handleNewChat = () => {
    window.location.reload();
  };

  return (
    <div className="flex h-screen bg-gray-950 text-gray-100 overflow-hidden">
      <Toaster position="top-right" />
      {/* Sidebar */}
      <Sidebar currentConvId={convId} onNewChat={handleNewChat} />

      {/* Main chat area */}
      <div className="flex flex-col flex-1 min-w-0">
        {/* Header */}
        <header className="flex items-center justify-between px-4 py-3 border-b border-gray-800 shrink-0">
          <div className="flex items-center gap-3">
            <h1 className="flex items-center text-lg tracking-tight select-none cursor-default">
              <span className="font-brand font-black text-rose-700 tracking-wide">GAMBA</span>
              <span className="font-mono font-medium text-indigo-100 ml-0.5 opacity-90">BOT</span>
            </h1>
            {shortId && (
              <span className="text-xs text-gray-600 font-mono">#{shortId}</span>
            )}
          </div>

          <div className="flex items-center gap-2">
            {/* Connection indicator */}
            <div
              className={`w-1.5 h-1.5 rounded-full ${
                isConnected ? "bg-emerald-500" : "bg-red-500"
              }`}
              title={isConnected ? "Connected" : "Reconnecting…"}
            />

            {/* Model badge */}
            <span className="text-xs text-gray-500 font-mono hidden sm:block">
              {settings.model}
            </span>

            {/* Settings button */}
            <button
              onClick={() => setSettingsOpen((v) => !v)}
              className={`p-1.5 rounded-lg transition-colors ${
                settingsOpen
                  ? "bg-gray-700 text-gray-200"
                  : "text-gray-500 hover:bg-gray-800 hover:text-gray-300"
              }`}
              aria-label="Settings"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className="w-4 h-4">
                <path strokeLinecap="round" strokeLinejoin="round" d="M10.343 3.94c.09-.542.56-.94 1.11-.94h1.093c.55 0 1.02.398 1.11.94l.149.894c.07.424.384.764.78.93.398.164.855.142 1.205-.108l.737-.527a1.125 1.125 0 0 1 1.45.12l.773.774c.39.389.44 1.002.12 1.45l-.527.737c-.25.35-.272.806-.107 1.204.165.397.505.71.93.78l.893.15c.543.09.94.559.94 1.109v1.094c0 .55-.397 1.02-.94 1.11l-.894.149c-.424.07-.764.383-.929.78-.165.398-.143.854.107 1.204l.527.738c.32.447.269 1.06-.12 1.45l-.774.773a1.125 1.125 0 0 1-1.449.12l-.738-.527c-.35-.25-.806-.272-1.203-.107-.398.165-.71.505-.781.929l-.149.894c-.09.542-.56.94-1.11.94h-1.094c-.55 0-1.019-.398-1.11-.94l-.148-.894c-.071-.424-.384-.764-.781-.93-.398-.164-.854-.142-1.204.108l-.738.527c-.447.32-1.06.269-1.45-.12l-.773-.774a1.125 1.125 0 0 1-.12-1.45l.527-.737c.25-.35.272-.806.108-1.204-.165-.397-.506-.71-.93-.78l-.894-.15c-.542-.09-.94-.56-.94-1.109v-1.094c0-.55.398-1.02.94-1.11l.894-.149c.424-.07.765-.383.93-.78.165-.398.143-.854-.108-1.204l-.526-.738a1.125 1.125 0 0 1 .12-1.45l.773-.773a1.125 1.125 0 0 1 1.45-.12l.737.527c.35.25.807.272 1.204.107.397-.165.71-.505.78-.929l.15-.894Z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" />
              </svg>
            </button>
          </div>
        </header>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-4 py-6 space-y-4">
          {messages.length === 0 && (
            <EmptyState model={settings.model} />
          )}

          {messages.map((msg) => (
            <Message key={msg.id} message={msg} sessionId={convId} />
          ))}

          {/* HITL prompt */}
          {hitl && (
            <HitlButtons hitl={hitl} onChoose={sendHitlResponse} />
          )}

          {/* Thinking indicator */}
          {isThinking && !hitl && (
            <div className="flex justify-start">
              <div className="flex items-center gap-2 bg-gray-800 rounded-xl px-4 py-2.5">
                <div className="flex gap-1">
                  {[0, 1, 2].map((i) => (
                    <div
                      key={i}
                      className="w-1.5 h-1.5 rounded-full bg-gray-400 animate-bounce"
                      style={{ animationDelay: `${i * 150}ms` }}
                    />
                  ))}
                </div>
                <span className="text-xs text-gray-500">Thinking…</span>
              </div>
            </div>
          )}

          <div ref={bottomRef} />
        </div>

        {/* Input */}
        <InputBar onSend={sendMessage} onStop={stopGeneration} disabled={isThinking || !isConnected} sendOnEnter={settings.sendOnEnter} />
      </div>

      {/* Settings drawer */}
      {settingsOpen && (
        <SettingsDrawer
          settings={settings}
          models={models}
          profiles={profiles}
          mcpServers={mcpServers}
          onChange={updateSettings}
          onClose={() => setSettingsOpen(false)}
        />
      )}
    </div>
  );
}

function EmptyState({ model }: { model: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center py-16 select-none">
      <div className="w-16 h-16 rounded-3xl bg-gradient-to-br from-rose-700 to-rose-900 shadow-lg shadow-rose-900/20 flex items-center justify-center text-3xl font-brand font-black text-white mb-5 ring-1 ring-white/10">
        GB
      </div>
      <h2 className="text-2xl flex items-center tracking-tight mb-2">
        <span className="font-brand font-black text-rose-700 tracking-wide">GAMBA</span>
        <span className="font-mono font-medium text-indigo-100 ml-0.5 opacity-90">BOT</span>
      </h2>
      <p className="text-sm text-gray-500 mb-6 max-w-xs leading-relaxed">
        Your turnkey ready, local-first AI workspace.
      </p>
      <div className="flex items-center gap-2 text-xs text-gray-400 bg-gray-900/80 px-4 py-2 rounded-full border border-gray-800/60 shadow-inner">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shrink-0 shadow-[0_0_8px_rgba(16,185,129,0.5)]" />
        {model}
      </div>
    </div>
  );
}
