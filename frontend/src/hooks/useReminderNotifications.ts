import { useEffect, useRef } from 'react';
import toast from 'react-hot-toast';

export function useReminderNotifications() {
  const pollingInterval = useRef<number | null>(null);

  useEffect(() => {
    const checkReminders = async () => {
      try {
        const res = await fetch('/api/reminders');
        if (!res.ok) return;
        
        const activeReminders: any[] = await res.json();
        const now = new Date();

        for (const reminder of activeReminders) {
          const remindTime = new Date(reminder.remind_at);
          if (now >= remindTime) {
            toast(`Reminder! You have a saved message waiting in chat ${reminder.session_id ? reminder.session_id.slice(0,6) : ''}`, {
              icon: '🔔',
              duration: 6000,
              style: { borderRadius: '10px', background: '#1f2937', color: '#fff' },
            });
            await fetch(`/api/reminders/${reminder.id}/complete`, { method: 'PUT' });
          }
        }
      } catch (err) {
        console.error("Failed to check reminders:", err);
      }
    };

    pollingInterval.current = window.setInterval(checkReminders, 30000);
    checkReminders();
    return () => { if (pollingInterval.current) clearInterval(pollingInterval.current); };
  }, []);
}