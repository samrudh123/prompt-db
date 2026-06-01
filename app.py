import os
from supabase import create_client, Client

supabase: Client = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_KEY"]
)

# ── Auth helper ──────────────────────────────────────────────────────
from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import HTTPException
from fastapi.responses import JSONResponse

security = HTTPBearer()

async def get_user(creds: HTTPAuthorizationCredentials = Depends(security)):
    """Verify the JWT from the frontend and return the user id."""
    try:
        user = supabase.auth.get_user(creds.credentials)
        return user.user.id
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

# ── Prompt CRUD endpoints ────────────────────────────────────────────
@app.get("/api/prompts")
async def list_prompts(user_id: str = Depends(get_user)):
    res = supabase.table("prompts").select("*").eq("user_id", user_id).order("created_at", desc=True).execute()
    return JSONResponse(res.data)

@app.post("/api/prompts")
async def create_prompt(body: dict, user_id: str = Depends(get_user)):
    res = supabase.table("prompts").insert({**body, "user_id": user_id}).execute()
    return JSONResponse(res.data[0])

@app.put("/api/prompts/{prompt_id}")
async def update_prompt(prompt_id: str, body: dict, user_id: str = Depends(get_user)):
    res = supabase.table("prompts").update(body).eq("id", prompt_id).eq("user_id", user_id).execute()
    return JSONResponse(res.data[0])

@app.delete("/api/prompts/{prompt_id}")
async def delete_prompt(prompt_id: str, user_id: str = Depends(get_user)):
    supabase.table("prompts").delete().eq("id", prompt_id).eq("user_id", user_id).execute()
    return JSONResponse({"ok": True})