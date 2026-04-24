import { useRef, useState } from "react";

interface Props {
  onSend: (content: string) => void;
  disabled?: boolean;
}

export function InputBar({ onSend, disabled }: Props) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const submit = () => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const onInput = (e: React.FormEvent<HTMLTextAreaElement>) => {
    const el = e.currentTarget;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  };

  return (
    <div className="p-4 border-t border-gray-800">
      <div className="flex items-end gap-2 bg-gray-800 rounded-xl border border-gray-700 focus-within:border-indigo-500 transition-colors px-3 py-2">
        <textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={onKeyDown}
          onInput={onInput}
          placeholder={disabled ? "Agent is thinking…" : "Message (Enter to send, Shift+Enter for newline)"}
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
      <p className="text-xs text-gray-600 mt-1 text-center">
        Shift+Enter for newline
      </p>
    </div>
  );
}
