import { useRef, useState } from "react";

interface Props {
  onSend: (content: string) => void;
  disabled?: boolean;
  sendOnEnter?: boolean;
}

const ACCEPTED = ".txt,.md,.pdf,.docx,.csv,.xlsx,.xls";

export function InputBar({ onSend, disabled, sendOnEnter = true }: Props) {
  const [value, setValue] = useState("");
  const [uploading, setUploading] = useState(false);
  const [uploadMsg, setUploadMsg] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      if (sendOnEnter && !e.shiftKey) { e.preventDefault(); submit(); }
      else if (!sendOnEnter && e.ctrlKey) { e.preventDefault(); submit(); }
    }
  };

  const onInput = (e: React.FormEvent<HTMLTextAreaElement>) => {
    const el = e.currentTarget;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  };

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    setUploading(true);
    setUploadMsg(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch("/rag/upload", { method: "POST", body: form });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        setUploadMsg(`Upload failed: ${err.detail ?? res.statusText}`);
      } else {
        const data = await res.json() as { source: string; chunks: number };
        setUploadMsg(`✓ Indexed "${data.source}" — ${data.chunks} chunks`);
      }
    } catch (err) {
      setUploadMsg(`Upload error: ${String(err)}`);
    } finally {
      setUploading(false);
      setTimeout(() => setUploadMsg(null), 5000);
    }
  };

  const hint = sendOnEnter ? "Shift+Enter for newline" : "Ctrl+Enter to send";

  return (
    <div className="px-4 pb-4 pt-2 border-t border-gray-800">
      {uploadMsg && (
        <p className="text-xs mb-2 px-1 text-gray-400">{uploadMsg}</p>
      )}
      <div className="flex items-end gap-2 bg-gray-800 rounded-xl border border-gray-700 focus-within:border-indigo-500 transition-colors px-3 py-2">
        {/* Upload button */}
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          disabled={uploading}
          title="Upload document to knowledge base"
          className="w-7 h-7 flex items-center justify-center rounded-lg text-gray-500 hover:text-gray-300 hover:bg-gray-700 disabled:opacity-40 transition-colors shrink-0"
        >
          {uploading ? (
            <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" d="M12 2a10 10 0 0 1 10 10" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} className="w-4 h-4">
              <path strokeLinecap="round" strokeLinejoin="round" d="M18.375 12.739l-7.693 7.693a4.5 4.5 0 01-6.364-6.364l10.94-10.94A3 3 0 1119.5 7.372L8.552 18.32m.009-.01l-.01.01m5.699-9.941l-7.81 7.81a1.5 1.5 0 002.112 2.13" />
            </svg>
          )}
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED}
          onChange={handleFile}
          className="hidden"
        />

        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          onInput={onInput}
          placeholder={disabled ? "Agent is thinking…" : `Message (${hint})`}
          disabled={disabled}
          rows={1}
          className="flex-1 bg-transparent text-sm text-gray-100 placeholder-gray-500 outline-none resize-none leading-relaxed py-0.5 disabled:opacity-50"
          style={{ minHeight: "24px", maxHeight: "200px" }}
        />

        <button
          onClick={submit}
          disabled={disabled || !value.trim()}
          className="w-8 h-8 flex items-center justify-center rounded-lg bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
          aria-label="Send message"
        >
          <svg viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4">
            <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
          </svg>
        </button>
      </div>
      <p className="text-xs text-gray-600 mt-1 text-center">{hint}</p>
    </div>
  );
}
