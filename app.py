import os
import json
from pathlib import Path
from typing import AsyncGenerator, Tuple

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from supabase import create_client, Client
from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

load_dotenv()

app = FastAPI()
supabase: Client = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_KEY"]
)

security = HTTPBearer()

NON_STREAM_TIMEOUT_SEC = float(os.getenv("NON_STREAM_TIMEOUT_SEC", "120"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

HERE = Path(__file__).resolve().parent


class PromptBody(BaseModel):
    title: str
    category: str
    prompt: str
    tags: list[str] = []

async def get_user(creds: HTTPAuthorizationCredentials = Depends(security)):
    """Verify the JWT from the frontend and return the user id."""
    try:
        user = supabase.auth.get_user(creds.credentials)
        return user.user.id
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

# ── Serve frontend ───────────────────────────────────────────────────
@app.get("/")
async def serve_index():
    return FileResponse(HERE / "index.html")

# ── Prompt CRUD endpoints ────────────────────────────────────────────
@app.get("/api/prompts")
async def list_prompts(user_id: str = Depends(get_user)):
    res = supabase.table("prompts").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
    return JSONResponse(res.data)

@app.post("/api/prompts")
async def create_prompt(body: PromptBody, user_id: str = Depends(get_user)):
    res = supabase.table("prompts").insert({**body.model_dump(), "user_id": user_id}).execute()
    return JSONResponse(res.data[0])

@app.put("/api/prompts/{prompt_id}")
async def update_prompt(prompt_id: str, body: PromptBody, user_id: str = Depends(get_user)):
    res = supabase.table("prompts").update(body.model_dump()).eq("id", prompt_id).eq("user_id", user_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return JSONResponse(res.data[0])

@app.delete("/api/prompts/{prompt_id}")
async def delete_prompt(prompt_id: str, user_id: str = Depends(get_user)):
    supabase.table("prompts").delete().eq("id", prompt_id).eq("user_id", user_id).execute()
    return JSONResponse({"ok": True})