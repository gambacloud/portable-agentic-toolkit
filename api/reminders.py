from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timezone
import uuid
from db.database import get_conn

router = APIRouter()

# --- Models ---
class ReminderCreate(BaseModel):
    session_id: str
    message_id: str
    remind_at: datetime
    note: Optional[str] = None

class Reminder(ReminderCreate):
    id: str
    created_at: datetime
    status: str

# --- Endpoints ---
@router.post("/api/reminders", response_model=Reminder)
async def create_reminder(reminder_in: ReminderCreate):
    new_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO reminders (id, session_id, message_id, remind_at, note, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (new_id, reminder_in.session_id, reminder_in.message_id, reminder_in.remind_at.isoformat(), reminder_in.note, "pending", created_at.isoformat())
        )
    return Reminder(id=new_id, created_at=created_at, status="pending", **reminder_in.model_dump())

@router.get("/api/reminders", response_model=List[Reminder])
async def get_active_reminders():
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM reminders WHERE status = 'pending'").fetchall()
    
    return [Reminder(
        id=row["id"], session_id=row["session_id"], message_id=row["message_id"],
        remind_at=datetime.fromisoformat(row["remind_at"]), note=row["note"],
        status=row["status"], created_at=datetime.fromisoformat(row["created_at"])
    ) for row in rows]

@router.put("/api/reminders/{reminder_id}/complete", response_model=Reminder)
async def complete_reminder(reminder_id: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Reminder not found")
        conn.execute("UPDATE reminders SET status = 'completed' WHERE id = ?", (reminder_id,))
        
        return Reminder(
            id=row["id"], session_id=row["session_id"], message_id=row["message_id"],
            remind_at=datetime.fromisoformat(row["remind_at"]), note=row["note"],
            status="completed", created_at=datetime.fromisoformat(row["created_at"])
        )