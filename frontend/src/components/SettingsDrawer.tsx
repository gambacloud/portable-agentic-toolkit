import { useEffect, useRef, useState } from "react";
import type { ChatSettings, Profile } from "../types";

interface Props {
  settings: ChatSettings;
  models: string[];
  profiles: Profile[];
  mcpServers: string[];
  onChange: (patch: Partial<ChatSettings>) => void;
  onClose: () => void;
}

interface RagDoc { source: string; chunks: number; }

export function SettingsDrawer({ settings, models, profiles, mcpServers, onChange, onClose }: Props) {
  const [ragDocs, setRagDocs] = useState<RagDoc[]>([]);

  useEffect(() => {
    fetch("/rag/documents")
      .then((r) => r.json())
      .then(setRagDocs)
      .catch(() => {});
  }, []);

  const deleteDoc = async (source: string) => {
    await fetch(`/rag/documents/${encodeURIComponent(source)}`, { method: "DELETE" });
    setRagDocs((prev) => prev.filter((d) => d.source !== source));
  };

  const toggleMcp = (name: string) => {
    const next = settings.activeMcps.includes(name)
      ? settings.activeMcps.filter((m) => m !== name)
      : [...settings.activeMcps, name];
    onChange({ activeMcps: next });
  };

  return (
    <div className="w-72 bg-gray-900 border-l border-gray-800 flex flex-col overflow-y-auto">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <h2 className="text-sm font-semibold text-gray-200">Settings</h2>
        <button
          onClick={onClose}
          className="text-gray-500 hover:text-gray-300 transition-colors text-lg leading-none"
        >
          ×
        </button>
      </div>

      <div className="p-4 space-y-5">
        {/* Model */}
        <div>
          <label className="text-xs font-medium text-gray-400 mb-1.5 block">LLM Model</label>
          <select
            value={settings.model}
            onChange={(e) => onChange({ model: e.target.value })}
            className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-indigo-500"
          >
            {models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>

        {/* Profile */}
        {profiles.length > 0 && (
          <div>
            <label className="text-xs font-medium text-gray-400 mb-1.5 block">
              Expert Profile
            </label>
            <select
              value={settings.profileId ?? ""}
              onChange={(e) => onChange({ profileId: e.target.value || null })}
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-indigo-500"
            >
              <option value="">(none)</option>
              {profiles.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Toggles */}
        <div className="space-y-3">
          <Toggle
            label="Show agent thinking"
            description="Display step-by-step reasoning"
            checked={settings.verbose}
            onChange={(v) => onChange({ verbose: v })}
          />
          <Toggle
            label="Multi-agent mode"
            description="Uses multiple specialized agents"
            checked={settings.multiAgent}
            onChange={(v) => onChange({ multiAgent: v })}
          />
          <Toggle
            label="Enter to send"
            description="Off = Ctrl+Enter to send"
            checked={settings.sendOnEnter}
            onChange={(v) => onChange({ sendOnEnter: v })}
          />
        </div>

        {/* MCP Servers */}
        {mcpServers.length > 0 && (
          <div>
            <label className="text-xs font-medium text-gray-400 mb-2 block">
              Active MCP Servers
            </label>
            <McpDropdown
              mcpServers={mcpServers}
              activeMcps={settings.activeMcps}
              onToggle={toggleMcp}
            />
          </div>
        )}

        {/* Knowledge Base */}
        <div>
          <label className="text-xs font-medium text-gray-400 mb-2 block">
            Knowledge Base {ragDocs.length > 0 && <span className="text-gray-600">({ragDocs.length})</span>}
          </label>
          {ragDocs.length === 0 ? (
            <p className="text-xs text-gray-600">No documents indexed. Use the paperclip in chat to upload.</p>
          ) : (
            <div className="space-y-1">
              {ragDocs.map((doc) => (
                <div key={doc.source} className="flex items-center justify-between gap-2 group">
                  <div className="min-w-0">
                    <p className="text-xs text-gray-300 truncate font-mono">{doc.source}</p>
                    <p className="text-xs text-gray-600">{doc.chunks} chunks</p>
                  </div>
                  <button
                    onClick={() => deleteDoc(doc.source)}
                    className="text-gray-600 hover:text-red-400 transition-colors shrink-0 opacity-0 group-hover:opacity-100"
                    title="Remove from knowledge base"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className="w-3.5 h-3.5">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Links */}
        <div className="pt-2 border-t border-gray-800">
          <p className="text-xs font-medium text-gray-400 mb-2">Quick Access</p>
          <div className="space-y-1">
            {[
              ["/mcp-ui", "MCP Servers"],
              ["/schedules-ui", "Schedules"],
              ["/outputs-ui", "Outputs"],
              ["/docs", "API Docs"],
            ].map(([href, label]) => (
              <a
                key={href}
                href={href}
                target="_blank"
                rel="noreferrer"
                className="block text-xs text-indigo-400 hover:text-indigo-300 transition-colors py-0.5"
              >
                {label} ↗
              </a>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function McpDropdown({
  mcpServers,
  activeMcps,
  onToggle,
}: {
  mcpServers: string[];
  activeMcps: string[];
  onToggle: (name: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const filtered = mcpServers.filter((s) =>
    s.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-sm text-gray-100 hover:border-gray-600 focus:outline-none focus:border-indigo-500 transition-colors"
      >
        <span className="text-xs text-gray-300">
          {activeMcps.length === 0 ? "None active" : `${activeMcps.length} active`}
        </span>
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          className={`w-3.5 h-3.5 text-gray-400 transition-transform ${open ? "rotate-180" : ""}`}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute z-50 mt-1 w-full bg-gray-800 border border-gray-700 rounded-lg shadow-xl overflow-hidden">
          <div className="p-2 border-b border-gray-700">
            <input
              autoFocus
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search..."
              className="w-full bg-gray-700 rounded px-2.5 py-1.5 text-xs text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>
          <div className="max-h-52 overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <p className="text-xs text-gray-500 px-3 py-2">No results</p>
            ) : (
              filtered.map((srv) => (
                <label
                  key={srv}
                  className="flex items-center gap-2.5 px-3 py-1.5 cursor-pointer hover:bg-gray-700 transition-colors"
                >
                  <input
                    type="checkbox"
                    checked={activeMcps.includes(srv)}
                    onChange={() => onToggle(srv)}
                    className="w-3.5 h-3.5 accent-indigo-500 shrink-0"
                  />
                  <span className="text-xs text-gray-300 font-mono">{srv}</span>
                </label>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Toggle({
  label,
  description,
  checked,
  onChange,
}: {
  label: string;
  description: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div>
        <p className="text-xs font-medium text-gray-300">{label}</p>
        <p className="text-xs text-gray-500">{description}</p>
      </div>
      <button
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`w-9 h-5 rounded-full transition-colors shrink-0 mt-0.5 ${
          checked ? "bg-indigo-600" : "bg-gray-700"
        }`}
      >
        <span
          className={`block w-3.5 h-3.5 rounded-full bg-white shadow transition-transform mx-0.5 ${
            checked ? "translate-x-4" : "translate-x-0"
          }`}
        />
      </button>
    </div>
  );
}
