import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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

HERE = Path(__file__).resolve().parent
load_dotenv(override=True)

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
EMAIL_FROM = os.getenv("EMAIL_FROM")

app = FastAPI()
supabase_admin: Client = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_SERVICE_KEY"]
)
supabase_auth: Client = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_ANON_KEY"]
)

security = HTTPBearer()

NON_STREAM_TIMEOUT_SEC = float(os.getenv("NON_STREAM_TIMEOUT_SEC", "120"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://samrudh123.github.io", "http://localhost:3000"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)

SYSTEM_USER_ID = os.environ["SYSTEM_USER_ID"]

class PromptBody(BaseModel):
    title: str
    category: str
    prompt: str
    tags: list[str] = []
    is_public: bool = False

class SignupBody(BaseModel):
    email: str
    username: str
    password: str

class RoleUpdateBody(BaseModel):
    role: str

class LoginBody(BaseModel):
    email_or_username: str
    password: str

async def get_user(creds: HTTPAuthorizationCredentials = Depends(security)):
    """Verify the JWT from the frontend and return the user id."""
    try:
        user = supabase_auth.auth.get_user(creds.credentials)
        return user.user.id
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

async def get_admin_user(user_id: str = Depends(get_user)):
    """Ensure the requesting user has the 'Bot' role."""
    res = supabase_admin.table("profiles").select("role").eq("id", user_id).single().execute()
    if not res.data or res.data.get("role") != "Bot":
        raise HTTPException(status_code=403, detail="Administrative privileges required")
    return user_id

# ── Auth endpoints ───────────────────────────────────────────────────
VALID_ROLES = {"Professor", "Lab-Admin", "MS", "Project-Staff", "Undergrad", "Interns", "Pending", "Server-Admin"}

@app.post("/api/signup")
async def signup(body: SignupBody):
    """Create a new user with username, email, and password."""
    # Check if username is already taken
    existing = supabase_admin.table("profiles").select("id").eq("username", body.username).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Username already taken")

    try:
        res = supabase_auth.auth.sign_up({
            "email": body.email,
            "password": body.password,
            "options": {
                "data": {
                    "username": body.username
                }
            }
        })
        if res.user is None:
            raise HTTPException(status_code=400, detail="Signup failed")
        return JSONResponse({
            "user_id": res.user.id,
            "email": body.email,
            "username": body.username
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/login")
async def login(body: LoginBody):
    """Login by email or username. If input has no '@', look up email from profiles."""
    email = body.email_or_username.strip()

    # If it doesn't look like an email, look up the username in profiles
    if "@" not in email:
        profile = supabase_admin.table("profiles").select("email").eq("username", email).execute()
        if not profile.data:
            raise HTTPException(status_code=401, detail="Username not found")
        email = profile.data[0]["email"]

    try:
        res = supabase_auth.auth.sign_in_with_password({
            "email": email,
            "password": body.password
        })
        return JSONResponse({
            "access_token": res.session.access_token,
            "refresh_token": res.session.refresh_token,
            "user": {
                "id": res.user.id,
                "email": res.user.email
            }
        })
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid credentials")

@app.get("/api/profile")
async def get_profile(user_id: str = Depends(get_user)):
    """Return the current user's profile (username, email, role)."""
    res = supabase_admin.table("profiles").select("*").eq("id", user_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Profile not found")
    profile = res.data[0]
    return JSONResponse({
        "id": profile["id"],
        "username": profile["username"],
        "email": profile["email"],
        "role": profile["role"],
        "created_at": profile.get("created_at")
    })

@app.get("/api/users/pending", response_model=list)
async def list_pending_users(admin_id: str = Depends(get_admin_user)):
    """List all users with 'Pending' role. Admin only."""
    res = supabase_admin.table("profiles").select("*").eq("role", "Pending").execute()
    return JSONResponse(res.data)

@app.get("/api/users/all", response_model=list)
async def list_all_users(admin_id: str = Depends(get_admin_user)):
    """List all non-Bot users so admin can manage their roles. Admin only."""
    try:
        res = supabase_admin.table("profiles") \
            .select("id, username, email, role, created_at") \
            .neq("role", "Bot") \
            .order("created_at", desc=True) \
            .execute()
        return JSONResponse(res.data if res.data else [])
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch users: {str(e)}")

async def send_role_assignment_email(user_email: str, role: str):
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM]):
        print("Email configuration is missing. Skipping email sending.")
        return

    subject = "Your role has been updated!"
    body = f"Hello,\n\nYour role in the Prompt Database has been updated to: {role}.\n\nBest regards,\nPrompt DB Admin"

    message = MIMEMultipart()
    message["From"] = EMAIL_FROM
    message["To"] = user_email
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message)
    except Exception as e:
        print(f"Failed to send email to {user_email} via Gmail SMTP: {e}")
        raise e

@app.patch("/api/users/{user_id}/role")
async def update_user_role(user_id: str, body: RoleUpdateBody, admin_id: str = Depends(get_admin_user)):
    """Update a user's role. Admin only."""
    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")
    
    res = supabase_admin.table("profiles").update({"role": body.role}).eq("id", user_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="User not found")
    
    user_email = res.data[0].get("email")
    if user_email:
        try:
            await send_role_assignment_email(user_email, body.role)
        except Exception as e:
            print(f"Failed to send notification email to {user_email}: {e}")

    return JSONResponse(res.data[0])

# ── Prompt CRUD endpoints ────────────────────────────────────────────
@app.get("/api/prompts")
async def list_prompts(user_id: str = Depends(get_user)):
    """List prompts that are public, owned by the user, or are system prompts."""
    # Fetch user role
    user_profile = supabase_admin.table("profiles").select("role").eq("id", user_id).single().execute()
    user_role = user_profile.data.get("role") if user_profile.data else 'Pending'

    if user_role == "Pending":
        # Only prompts owned by Bot users for Pending/unverified users
        # We use !inner to filter by the joined profile role
        res = supabase_admin.table("prompts").select("*, profiles!inner(username, role)").eq("profiles.role", "Bot").execute()
    else:
        # Combined filter: is_public=true OR owner=user OR owner=system (Bot)
        query_filter = f"is_public.eq.true,user_id.eq.{user_id}"
        if SYSTEM_USER_ID:
            query_filter += f",user_id.eq.{SYSTEM_USER_ID}"
        res = supabase_admin.table("prompts").select("*, profiles(username, role)").or_(query_filter).execute()
    data = res.data
    
    # Mark system prompts and flatten profile data
    for p in data:
        profile_data = p.get("profiles")
        
        # Supabase joins can return a list or a single object
        profile = None
        if isinstance(profile_data, list) and len(profile_data) > 0:
            profile = profile_data[0]
        elif isinstance(profile_data, dict):
            profile = profile_data
        
        if profile:
            p["username"] = profile.get("username")
            p["role"] = profile.get("role")
        
        # A prompt is a system prompt if its owner has the 'Bot' role
        p["is_system"] = (profile and profile.get("role") == "Bot")
        
    data.sort(key=lambda x: x.get('created_at') or x.get('created', ''), reverse=True)
    return JSONResponse(data)


@app.post("/api/prompts")
async def create_prompt(body: PromptBody, user_id: str = Depends(get_user)):
    res = supabase_admin.table("prompts").insert({**body.model_dump(), "user_id": user_id}).execute()
    return JSONResponse(res.data[0])

class PublicToggleBody(BaseModel):
    is_public: bool

@app.patch("/api/prompts/{prompt_id}/public")
async def toggle_public(prompt_id: str, body: PublicToggleBody, user_id: str = Depends(get_user)):
    """Toggle the public status of a prompt."""
    res = supabase_admin.table("prompts").update({"is_public": body.is_public}).eq("id", prompt_id).eq("user_id", user_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Prompt not found or unauthorized")
    return JSONResponse(res.data[0])

@app.put("/api/prompts/{prompt_id}")
async def update_prompt(prompt_id: str, body: PromptBody, user_id: str = Depends(get_user)):
    res = supabase_admin.table("prompts").update(body.model_dump()).eq("id", prompt_id).eq("user_id", user_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return JSONResponse(res.data[0])

@app.delete("/api/prompts/{prompt_id}")
async def delete_prompt(prompt_id: str, user_id: str = Depends(get_user)):
    supabase_admin.table("prompts").delete().eq("id", prompt_id).eq("user_id", user_id).execute()
    return JSONResponse({"ok": True})