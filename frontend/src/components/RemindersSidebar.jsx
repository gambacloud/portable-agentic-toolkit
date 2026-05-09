import React, { useEffect, useState } from 'react';

export function RemindersSidebar({ onNavigateToMessage }) {
  const [reminders, setReminders] = useState([]);

  const fetchReminders = async () => {
    try {
      const res = await fetch('/api/reminders');
      if (res.ok) {
        const data = await res.json();
        setReminders(data);
      }
    } catch (err) {
      console.error("Failed to fetch reminders", err);
    }
  };

  useEffect(() => {
    fetchReminders();
    // Refresh list every 30 seconds
    const interval = setInterval(fetchReminders, 30000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="w-64 bg-gray-50 border-l border-gray-200 h-full p-4 overflow-y-auto">
      <h2 className="font-bold text-lg mb-4 flex items-center gap-2">🔔 Reminders</h2>
      {reminders.length === 0 ? (
        <p className="text-gray-400 text-sm">No pending reminders.</p>
      ) : (
        <ul className="space-y-3">
          {reminders.map((reminder) => (
            <li key={reminder.id} className="bg-white p-3 rounded-md shadow-sm border border-gray-100 cursor-pointer hover:border-blue-300 transition-colors" onClick={() => onNavigateToMessage(reminder.session_id, reminder.message_id)}>
              <div className="text-sm font-medium text-gray-800">Chat: {reminder.session_id ? reminder.session_id.slice(0,8) : 'Unknown'}...</div>
              <div className="text-xs text-gray-500 mt-1">For: {new Date(reminder.remind_at).toLocaleTimeString()}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}