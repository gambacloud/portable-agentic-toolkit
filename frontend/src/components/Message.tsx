import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage } from "../types";
import { RemindMeButton } from "./RemindMeButton";

interface Props {
  message: ChatMessage & { id?: string };
  sessionId?: string | null;
}

function fmtTime(ts: number | undefined): string | null {
  if (!ts) return null;
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function Message({ message, sessionId }: Props) {
  const { role, content, stepName, draftTitle, draftLanguage, fileUrl, fileName, ts } = message;

  if (role === "step") return <StepCard name={stepName ?? "Step"} content={content} />;
  if (role === "draft") return <DraftCard title={draftTitle ?? "Draft"} content={content} language={draftLanguage ?? ""} />;
  if (role === "file") return <FileCard title={content} url={fileUrl ?? ""} filename={fileName ?? "download"} />;
  if (role === "system") return <SystemMessage content={content} />;
  if (role === "error") return <ErrorMessage content={content} />;

  const isUser = role === "user";
  const timeStr = fmtTime(ts);

  return (
    <div className={`flex gap-3 ${isUser ? "justify-end" : "justify-start"} group`}>
      {!isUser && (
        <div className="w-7 h-7 rounded-full bg-indigo-600 flex items-center justify-center text-xs font-bold shrink-0 mt-0.5">
          AI
        </div>
      )}

      {isUser && (
        <div className="opacity-0 group-hover:opacity-100 transition-opacity flex items-start pt-1">
          <RemindMeButton sessionId={sessionId || "local"} messageId={message.id || "unknown"} />
        </div>
      )}

      <div className={`flex flex-col max-w-[75%] gap-0.5 ${isUser ? "items-end" : "items-start"}`}>
        <div
          className={`rounded-2xl px-4 py-2.5 text-sm ${
            isUser
              ? "bg-indigo-600 text-white rounded-tr-sm"
              : "bg-gray-800 text-gray-100 rounded-tl-sm"
          }`}
        >
          {isUser ? (
            <span className="whitespace-pre-wrap">{content}</span>
          ) : (
            <div className="prose-chat">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
            </div>
          )}
        </div>
        {timeStr && (
          <span className="text-[10px] text-gray-400 px-1">{timeStr}</span>
        )}
      </div>

      {!isUser && (
        <div className="opacity-0 group-hover:opacity-100 transition-opacity flex items-start pt-1">
          <RemindMeButton sessionId={sessionId || "local"} messageId={message.id || "unknown"} />
        </div>
      )}

      {isUser && (
        <div className="w-7 h-7 rounded-full bg-gray-600 flex items-center justify-center text-xs font-bold shrink-0 mt-0.5">
          U
        </div>
      )}
    </div>
  );
}

function StepCard({ name, content }: { name: string; content: string }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="flex justify-start">
      <div className="max-w-[85%] w-full">
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-2 text-xs text-gray-500 hover:text-gray-300 transition-colors py-1 px-2 rounded bg-gray-900 border border-gray-800 w-full text-left"
        >
          <span className="text-gray-600">{open ? "▼" : "▶"}</span>
          <span className="font-mono truncate">{name}</span>
        </button>
        {open && (
          <div className="mt-1 bg-gray-900 border border-gray-800 rounded-lg p-3 text-xs font-mono text-gray-400 whitespace-pre-wrap overflow-x-auto">
            {content}
          </div>
        )}
      </div>
    </div>
  );
}

function DraftCard({ title, content, language }: { title: string; content: string; language: string }) {
  const [copied, setCopied] = useState(false);
  const [logoUrl, setLogoUrl] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/settings")
      .then((r) => r.json())
      .then((d) => setLogoUrl(d.logo_url ?? null))
      .catch(() => {});
  }, []);

  const copy = () => {
    navigator.clipboard.writeText(content).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  };

  return (
    <div className="flex justify-start w-full">
      <div className="w-full max-w-[90%] bg-gray-900 border border-gray-700 rounded-xl overflow-hidden">
        <div className="flex items-center justify-between px-4 py-2 bg-gray-800 border-b border-gray-700">
          <div className="flex items-center gap-2 min-w-0">
            {logoUrl && <img src={logoUrl} alt="" className="w-4 h-4 object-contain shrink-0" />}
            <span className="text-xs font-semibold text-gray-300 truncate">{title}</span>
          </div>
          <div className="flex items-center gap-2">
            {language && (
              <span className="text-xs text-gray-500 font-mono">{language}</span>
            )}
            <button
              onClick={copy}
              className="text-xs text-gray-400 hover:text-gray-200 transition-colors px-2 py-0.5 rounded bg-gray-700 hover:bg-gray-600"
            >
              {copied ? "Copied!" : "Copy"}
            </button>
          </div>
        </div>
        <pre className="p-4 text-xs font-mono text-gray-300 overflow-x-auto whitespace-pre-wrap leading-relaxed">
          {content}
        </pre>
      </div>
    </div>
  );
}

function FileCard({ title, url, filename }: { title: string; url: string; filename: string }) {
  return (
    <div className="flex justify-start w-full">
      <div className="w-full max-w-[90%] bg-gray-900 border border-gray-700 rounded-xl overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 gap-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="text-lg shrink-0">📄</span>
            <div className="min-w-0">
              <p className="text-xs font-semibold text-gray-300 truncate">{title}</p>
              <p className="text-xs text-gray-500 truncate">{filename}</p>
            </div>
          </div>
          <a
            href={url}
            download={filename}
            className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors px-3 py-1.5 rounded bg-gray-800 hover:bg-gray-700 shrink-0"
          >
            ⬇ Download
          </a>
        </div>
      </div>
    </div>
  );
}

function SystemMessage({ content }: { content: string }) {
  return (
    <div className="flex justify-center">
      <div className="max-w-[80%] bg-gray-900 border border-gray-700 rounded-xl px-4 py-2.5">
        <div className="prose-chat text-xs text-gray-400">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        </div>
      </div>
    </div>
  );
}

function ErrorMessage({ content }: { content: string }) {
  return (
    <div className="flex justify-start">
      <div className="max-w-[75%] bg-red-950 border border-red-800 rounded-xl px-4 py-2.5">
        <p className="text-xs text-red-300">⚠ {content}</p>
      </div>
    </div>
  );
}
