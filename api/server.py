"""
FastAPI persistence API — mounted at /api on the Chainlit server.

Identity: pass X-User-ID header on every request.
Docs:     http://localhost:8000/api/docs
"""
import os

import db.queries as q
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

BOT_NAME = os.getenv("BOT_NAME", "Gambabot")

api = FastAPI(
    title=f"{BOT_NAME} API",
    version="1.0.0",
    docs_url="/docs",
    redoc_url=None,
    openapi_url="/openapi.json",
)


# ── Schemas ───────────────────────────────────────────────────────────────────


class ConversationCreate(BaseModel):
    model: str = "llama3.2"
    title: str | None = None


class MessageAppend(BaseModel):
    role: str
    content: str


class ProfileCreate(BaseModel):
    name: str
    role: str | None = None
    goal: str | None = None
    backstory: str | None = None
    is_default: bool = False


class ProfileUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    goal: str | None = None
    backstory: str | None = None
    is_default: bool | None = None


# ── Identity dependency ───────────────────────────────────────────────────────


def current_user(x_user_id: str = Header(default="anonymous")) -> str:
    return x_user_id


# ── Health ────────────────────────────────────────────────────────────────────


@api.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "bot": BOT_NAME}


# ── Users ─────────────────────────────────────────────────────────────────────


@api.get("/users/me", tags=["users"])
def get_me(user_id: str = Depends(current_user)):
    return q.upsert_user(user_id)


@api.get("/users/me/conversations", tags=["users"])
def my_conversations(limit: int = 20, user_id: str = Depends(current_user)):
    return q.list_conversations(user_id, limit)


# ── Conversations ─────────────────────────────────────────────────────────────


@api.post("/conversations", status_code=201, tags=["conversations"])
def start_conversation(body: ConversationCreate, user_id: str = Depends(current_user)):
    q.upsert_user(user_id)
    conv_id = q.create_conversation(user_id, body.model, body.title)
    return {"id": conv_id}


@api.get("/conversations/{conv_id}", tags=["conversations"])
def get_conversation(conv_id: str):
    conv = q.get_conversation(conv_id)
    if not conv:
        raise HTTPException(404, "Conversation not found")
    return conv


@api.post("/conversations/{conv_id}/messages", status_code=201, tags=["conversations"])
def add_message(conv_id: str, body: MessageAppend):
    if not q.get_conversation(conv_id):
        raise HTTPException(404, "Conversation not found")
    q.append_message(conv_id, body.role, body.content)
    return {"ok": True}


# ── System Profiles ───────────────────────────────────────────────────────────


@api.get("/profiles", tags=["profiles"])
def list_profiles():
    return q.list_profiles()


@api.post("/profiles", status_code=201, tags=["profiles"])
def create_profile(body: ProfileCreate):
    return q.create_profile(
        body.name, body.role, body.goal, body.backstory, body.is_default
    )


@api.put("/profiles/{profile_id}", tags=["profiles"])
def update_profile(profile_id: str, body: ProfileUpdate):
    updated = q.update_profile(profile_id, **body.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(404, "Profile not found")
    return updated


@api.delete("/profiles/{profile_id}", status_code=204, tags=["profiles"])
def delete_profile(profile_id: str):
    if not q.delete_profile(profile_id):
        raise HTTPException(404, "Profile not found")
