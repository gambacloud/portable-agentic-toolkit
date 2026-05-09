import { useState } from 'react';

interface Props {
  sessionId: string;
  messageId: string;
  onReminderCreated?: () => void;
}

export function RemindMeButton({ sessionId, messageId, onReminderCreated }: Props) {
  const [isOpen, setIsOpen] = useState(false);

  const scheduleReminder = async (minutesFromNow: number) => {
    const remindAt = new Date(Date.now() + minutesFromNow * 60000);
    
    try {
      const res = await fetch('/api/reminders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          message_id: messageId,
          remind_at: remindAt.toISOString(),
        }),
      });
      
      if (res.ok) {
        setIsOpen(false);
        if (onReminderCreated) onReminderCreated();
      } else {
        console.error("Failed to schedule reminder");
      }
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="relative inline-block text-left">
      <button 
        onClick={() => setIsOpen(!isOpen)}
        className="p-1 text-gray-500 hover:text-indigo-400 transition-colors"
        title="Remind me later"
      >
        🕒
      </button>

      {isOpen && (
        <div className="absolute right-0 mt-2 w-48 bg-gray-900 border border-gray-700 rounded-xl shadow-lg z-50 overflow-hidden">
          <div className="py-1">
            <button className="block w-full text-left px-4 py-2 text-sm text-gray-300 hover:bg-gray-800 hover:text-gray-100 transition-colors" onClick={() => scheduleReminder(20)}>In 20 minutes</button>
            <button className="block w-full text-left px-4 py-2 text-sm text-gray-300 hover:bg-gray-800 hover:text-gray-100 transition-colors" onClick={() => scheduleReminder(60)}>In 1 hour</button>
            <button className="block w-full text-left px-4 py-2 text-sm text-gray-300 hover:bg-gray-800 hover:text-gray-100 transition-colors" onClick={() => scheduleReminder(24 * 60)}>Tomorrow</button>
          </div>
        </div>
      )}
    </div>
  );
}