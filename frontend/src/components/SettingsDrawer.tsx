import type { ChatSettings, Profile } from "../types";

interface Props {
  settings: ChatSettings;
  models: string[];
  profiles: Profile[];
  mcpServers: string[];
  onChange: (patch: Partial<ChatSettings>) => void;
  onClose: () => void;
}

export function SettingsDrawer({ settings, models, profiles, mcpServers, onChange, onClose }: Props) {
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
        </div>

        {/* MCP Servers */}
        {mcpServers.length > 0 && (
          <div>
            <label className="text-xs font-medium text-gray-400 mb-2 block">
              Active MCP Servers
            </label>
            <div className="space-y-1.5">
              {mcpServers.map((srv) => (
                <label key={srv} className="flex items-center gap-2 cursor-pointer group">
                  <input
                    type="checkbox"
                    checked={settings.activeMcps.includes(srv)}
                    onChange={() => toggleMcp(srv)}
                    className="w-3.5 h-3.5 accent-indigo-500"
                  />
                  <span className="text-xs text-gray-300 group-hover:text-gray-100 transition-colors font-mono">
                    {srv}
                  </span>
                </label>
              ))}
            </div>
          </div>
        )}

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
