import os
import json
import re
import smtplib
import secrets
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import AsyncGenerator, Tuple, Optional

import httpx
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from supabase import create_client, Client
from fastapi import Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

HERE = Path(__file__).resolve().parent
# Load .env from next to this file, not from the CWD, so the server behaves
# the same whether it is started from backend/ or from the repo root.
load_dotenv(HERE / ".env", override=True)

SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
EMAIL_FROM = os.getenv("EMAIL_FROM")
# Where the verification-email link should send users (your GitHub Pages URL)
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://samrudh123.github.io/prompt-db").rstrip("/")

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

# Roles that may manage other users' data (edit/delete any prompt, manage roles)
ADMIN_ROLES = {"Bot", "Server-Admin"}

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

class ResendVerificationBody(BaseModel):
    email: str

# ── Auth dependencies ────────────────────────────────────────────────

async def get_auth_user(creds: HTTPAuthorizationCredentials = Depends(security)):
    """Verify the JWT from the frontend and return the full auth user object."""
    try:
        user = supabase_auth.auth.get_user(creds.credentials)
        return user.user
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

async def get_user(auth_user = Depends(get_auth_user)):
    """Return just the user id (kept for backwards compatibility)."""
    return auth_user.id

def _derive_username(auth_user) -> str:
    """Build a username for OAuth users who never picked one."""
    meta = auth_user.user_metadata or {}
    base = (
        meta.get("username")
        or meta.get("user_name")
        or meta.get("preferred_username")
        or (auth_user.email or "").split("@")[0]
        or f"user_{auth_user.id[:8]}"
    )
    # keep it simple/safe: letters, digits, dot, dash, underscore
    base = re.sub(r"[^a-zA-Z0-9._-]", "", base) or f"user_{auth_user.id[:8]}"

    # ensure uniqueness in profiles
    candidate = base
    existing = supabase_admin.table("profiles").select("id").eq("username", candidate).execute()
    if existing.data:
        candidate = f"{base}_{auth_user.id[:6]}"
    return candidate

def fetch_profile(user_id: str) -> Optional[dict]:
    """Return the user's profile row, or None if they never registered.
    (Optional[dict] instead of dict|None: the latter crashes Python 3.9.)"""
    res = supabase_admin.table("profiles").select("*").eq("id", user_id).execute()
    return res.data[0] if res.data else None

def create_profile(auth_user, username: Optional[str] = None) -> dict:
    """Create a Pending profile (Google/OAuth signups)."""
    profile = {
        "id": auth_user.id,
        "email": auth_user.email,
        "username": username or _derive_username(auth_user),
        "role": "Pending",
    }
    created = supabase_admin.table("profiles").upsert(profile, on_conflict="id").execute()
    if created.data:
        return created.data[0]
    raise HTTPException(status_code=500, detail="Could not create profile")

async def get_profile_dep(auth_user = Depends(get_auth_user)) -> dict:
    """Dependency that requires a registered profile."""
    profile = fetch_profile(auth_user.id)
    if profile is None:
        raise HTTPException(
            status_code=403,
            detail="No Prompt DB account found. Please sign up first."
        )
    return profile

async def get_admin_user(profile: dict = Depends(get_profile_dep)):
    """Ensure the requesting user has an admin role."""
    if profile.get("role") not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Administrative privileges required")
    return profile["id"]

# ── Auth endpoints ───────────────────────────────────────────────────
VALID_ROLES = {"Professor", "Lab-Admin", "MS", "Project-Staff", "Undergrad", "Interns", "Pending", "Server-Admin"}

class VerifyBody(BaseModel):
    intent: str = "login"  # 'login' or 'signup'

class CompleteSignupBody(BaseModel):
    token: str
    username: str

SIGNUP_TOKEN_TTL_HOURS = 24

def _get_pending_signup_token(auth_user) -> Optional[str]:
    """Return the user's unexpired signup token, or None."""
    meta = auth_user.user_metadata or {}
    token = meta.get("signup_token")
    expires = meta.get("signup_token_expires")
    if not token or not expires:
        return None
    try:
        if datetime.fromisoformat(expires) < datetime.now(timezone.utc):
            return None
    except Exception:
        return None
    return token

def send_google_signup_email(user_email: str, link: str):
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM]):
        print("Email configuration is missing. Skipping email sending.")
        return

    subject = "Verify your email to finish signing up — Prompt DB"
    body = (
        "Hello,\n\n"
        "You started signing up for the Prompt Database with your Google account.\n"
        "Click the link below to verify your email and choose your username:\n\n"
        f"{link}\n\n"
        f"This link expires in {SIGNUP_TOKEN_TTL_HOURS} hours. "
        "If you didn't request this, you can ignore this email.\n\n"
        "Best regards,\nPrompt DB System"
    )

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
        print(f"Failed to send signup verification email to {user_email}: {e}")

@app.post("/api/auth/verify")
async def verify_session(body: VerifyBody, background_tasks: BackgroundTasks, auth_user = Depends(get_auth_user)):
    """
    Called by the frontend after every session is established.
    - Registered user -> return their profile (any intent).
    - New Google user, intent 'signup' -> email an SMTP verification link;
      profile is created later at /api/auth/complete-signup once they've
      clicked the link and chosen a username.
    - New Google user, intent 'login' -> delete the just-created auth user
      and reject: they must sign up first. (If they have a pending
      verification email, keep the account and remind them instead.)
    """
    profile = fetch_profile(auth_user.id)
    if profile:
        return JSONResponse({"registered": True, "profile": {
            "id": profile["id"],
            "username": profile["username"],
            "role": profile["role"],
        }})

    pending_token = _get_pending_signup_token(auth_user)

    if body.intent == "signup":
        # Reuse an unexpired token so previously emailed links keep working;
        # otherwise mint a fresh one.
        token = pending_token or secrets.token_urlsafe(32)
        if not pending_token:
            expires = (datetime.now(timezone.utc) + timedelta(hours=SIGNUP_TOKEN_TTL_HOURS)).isoformat()
            supabase_admin.auth.admin.update_user_by_id(auth_user.id, {
                "user_metadata": {"signup_token": token, "signup_token_expires": expires}
            })
        link = f"{FRONTEND_URL}/?signup_token={token}"
        background_tasks.add_task(send_google_signup_email, auth_user.email, link)
        return JSONResponse({
            "registered": False,
            "verification_required": True,
            "email": auth_user.email
        })

    # intent == 'login'
    if pending_token:
        # Mid-signup: don't delete their account, just point them back
        raise HTTPException(
            status_code=403,
            detail="Please verify your email to finish signing up — check your inbox for the verification link."
        )

    # No account at all: undo the OAuth-created auth user so a later
    # "Sign up with Google" starts clean.
    try:
        supabase_admin.auth.admin.delete_user(auth_user.id)
    except Exception as e:
        print(f"Failed to delete unregistered OAuth user {auth_user.id}: {e}")
    raise HTTPException(
        status_code=403,
        detail="No Prompt DB account found for this Google account. Please sign up first."
    )

@app.post("/api/auth/complete-signup")
async def complete_signup(body: CompleteSignupBody, background_tasks: BackgroundTasks, auth_user = Depends(get_auth_user)):
    """Finish a Google signup: verify the emailed token, set the chosen
    username, and create the (Pending) profile."""
    if fetch_profile(auth_user.id):
        raise HTTPException(status_code=400, detail="Account already registered")

    pending_token = _get_pending_signup_token(auth_user)
    if not pending_token or not secrets.compare_digest(pending_token, body.token):
        raise HTTPException(status_code=403, detail="Invalid or expired verification link. Please sign up again to receive a new one.")

    username = body.username.strip()
    if '@' in username:
        raise HTTPException(status_code=400, detail="Username cannot contain '@'")
    if not re.fullmatch(r"[a-zA-Z0-9._-]{3,30}", username):
        raise HTTPException(status_code=400, detail="Username must be 3-30 characters (letters, digits, . _ -)")
    existing = supabase_admin.table("profiles").select("id").eq("username", username).execute()
    if existing.data:
        raise HTTPException(status_code=400, detail="Username already taken")

    profile = create_profile(auth_user, username=username)

    # Notify the admin that a role assignment is needed (same as normal signup)
    background_tasks.add_task(send_signup_notification, auth_user.email, username, "Google")

    # Clear the used token
    try:
        supabase_admin.auth.admin.update_user_by_id(auth_user.id, {
            "user_metadata": {"signup_token": None, "signup_token_expires": None}
        })
    except Exception as e:
        print(f"Failed to clear signup token for {auth_user.id}: {e}")

    return JSONResponse({"registered": True, "profile": {
        "id": profile["id"],
        "username": profile["username"],
        "role": profile["role"],
    }})

@app.post("/api/auth/cancel-signup")
async def cancel_signup(auth_user = Depends(get_auth_user)):
    """Abort an incomplete Google signup: if the user never finished
    verification (no profile yet), delete the auth user so nothing
    unverified lingers in Supabase."""
    if fetch_profile(auth_user.id):
        # Registered users are never deleted here
        return JSONResponse({"ok": True, "deleted": False})
    try:
        supabase_admin.auth.admin.delete_user(auth_user.id)
        return JSONResponse({"ok": True, "deleted": True})
    except Exception as e:
        print(f"Failed to delete incomplete signup {auth_user.id}: {e}")
        return JSONResponse({"ok": True, "deleted": False})

@app.post("/api/signup")
async def signup(body: SignupBody, background_tasks: BackgroundTasks):
    """Create a new user with username, email, and password.
    With 'Confirm email' enabled in Supabase, no session is returned until
    the user clicks the verification link sent to their inbox."""
    if '@' in body.username:
        raise HTTPException(status_code=400, detail="Username cannot contain '@'")

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

        # Send notification in background to avoid blocking response
        background_tasks.add_task(send_signup_notification, body.email, body.username)

        # When email confirmation is enabled, session is None until verified
        needs_verification = res.session is None

        return JSONResponse({
            "user_id": res.user.id,
            "email": body.email,
            "username": body.username,
            "needs_verification": needs_verification,
            "message": "Check your email to verify your account before logging in."
                       if needs_verification else "Signup successful."
        })
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/resend-verification")
async def resend_verification(body: ResendVerificationBody):
    """Resend the email verification link."""
    try:
        supabase_auth.auth.resend({"type": "signup", "email": body.email})
        return JSONResponse({"ok": True, "message": "Verification email resent."})
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
        # Surface unverified-email as a distinct, actionable error
        if "email not confirmed" in str(e).lower():
            raise HTTPException(
                status_code=403,
                detail="Email not verified. Please check your inbox for the verification link."
            )
        raise HTTPException(status_code=401, detail="Invalid credentials")

@app.get("/api/profile")
async def get_profile(profile: dict = Depends(get_profile_dep)):
    """Return the current user's profile (username, email, role).
    Also auto-creates the profile for first-time Google/OAuth sign-ins."""
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

async def send_signup_notification(user_email: str, username: str, method: str = "Email/Password"):
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD, EMAIL_FROM]):
        print("Email configuration is missing. Skipping email sending.")
        return

    subject = "New User Signup — Role Assignment Needed"
    body = (
        "Hello Admin,\n\n"
        "A new user has signed up for the Prompt Database:\n\n"
        f"Username: {username}\n"
        f"Email: {user_email}\n"
        f"Signup method: {method}\n\n"
        "They are currently in the 'Pending' role. Please visit the Admin Panel "
        "to assign them an appropriate role.\n\n"
        "Best regards,\nPrompt DB System"
    )

    message = MIMEMultipart()
    message["From"] = EMAIL_FROM
    message["To"] = EMAIL_FROM # Sending to self
    message["Subject"] = subject
    message.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(message)
    except Exception as e:
        print(f"Failed to send signup notification to {EMAIL_FROM}: {e}")
        raise e

@app.patch("/api/users/{user_id}/role")
async def update_user_role(user_id: str, body: RoleUpdateBody, background_tasks: BackgroundTasks, admin_id: str = Depends(get_admin_user)):
    """Update a user's role. Admin only."""
    if body.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail="Invalid role")

    res = supabase_admin.table("profiles").update({"role": body.role}).eq("id", user_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="User not found")

    user_email = res.data[0].get("email")
    if user_email:
        # Send email in background to avoid blocking the response
        background_tasks.add_task(send_role_assignment_email, user_email, body.role)

    return JSONResponse(res.data[0])

# ── Prompt CRUD endpoints ────────────────────────────────────────────
@app.get("/api/prompts")
async def list_prompts(profile: dict = Depends(get_profile_dep)):
    """List prompts that are public, owned by the user, or are system prompts.
    Admins (Bot / Server-Admin) see ALL prompts so they can manage them."""
    user_id = profile["id"]
    user_role = profile.get("role") or "Pending"

    if user_role in ADMIN_ROLES:
        # Admins see everything
        res = supabase_admin.table("prompts").select("*, profiles(username, role)").execute()
    elif user_role == "Pending":
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
        prof = None
        if isinstance(profile_data, list) and len(profile_data) > 0:
            prof = profile_data[0]
        elif isinstance(profile_data, dict):
            prof = profile_data

        if prof:
            p["username"] = prof.get("username")
            p["role"] = prof.get("role")

        # A prompt is a system prompt if its owner has the 'Bot' role
        p["is_system"] = (prof and prof.get("role") == "Bot")

        # Tell the frontend whether the current user may edit/delete this prompt
        p["can_manage"] = (p.get("user_id") == user_id) or (user_role in ADMIN_ROLES)

    data.sort(key=lambda x: x.get('created_at') or x.get('created', ''), reverse=True)
    return JSONResponse(data)


@app.post("/api/prompts")
async def create_prompt(body: PromptBody, user_id: str = Depends(get_user)):
    res = supabase_admin.table("prompts").insert({**body.model_dump(), "user_id": user_id}).execute()
    return JSONResponse(res.data[0])

class PublicToggleBody(BaseModel):
    is_public: bool

@app.patch("/api/prompts/{prompt_id}/public")
async def toggle_public(prompt_id: str, body: PublicToggleBody, profile: dict = Depends(get_profile_dep)):
    """Toggle the public status of a prompt. Owners or admins only."""
    query = supabase_admin.table("prompts").update({"is_public": body.is_public}).eq("id", prompt_id)
    if profile.get("role") not in ADMIN_ROLES:
        query = query.eq("user_id", profile["id"])
    res = query.execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Prompt not found or unauthorized")
    return JSONResponse(res.data[0])

@app.put("/api/prompts/{prompt_id}")
async def update_prompt(prompt_id: str, body: PromptBody, profile: dict = Depends(get_profile_dep)):
    """Update a prompt. Owners can edit their own; admins can edit any."""
    query = supabase_admin.table("prompts").update(body.model_dump()).eq("id", prompt_id)
    if profile.get("role") not in ADMIN_ROLES:
        query = query.eq("user_id", profile["id"])
    res = query.execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Prompt not found or unauthorized")
    return JSONResponse(res.data[0])

@app.delete("/api/prompts/{prompt_id}")
async def delete_prompt(prompt_id: str, profile: dict = Depends(get_profile_dep)):
    """Delete a prompt. Owners can delete their own; admins can delete any."""
    query = supabase_admin.table("prompts").delete().eq("id", prompt_id)
    if profile.get("role") not in ADMIN_ROLES:
        query = query.eq("user_id", profile["id"])
    res = query.execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Prompt not found or unauthorized")
    return JSONResponse({"ok": True})