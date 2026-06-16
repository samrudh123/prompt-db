# Adaptive Prompt Database

An intelligent, role-based repository for managing and running complex AI prompts. This application allows research teams and laboratories to collaborate on a shared library of optimized prompts, complete with dynamic variable injection and a specialized execution environment.

## 🚀 Key Features

### 🔐 Authentication & RBAC
- **Role-Based Access Control (RBAC):** Granular permissions for different users (Professor, Lab-Admin, MS, Project-Staff, Undergrad, Interns, Pending, Bot, and Server-Admin).
- **Secure Sign-up/Login:** Integrated with Supabase Auth for secure session management.
- **Password Recovery:** Native password reset flow allowing users to securely recover account access via email.
- **Admin Dashboard:** A dedicated management interface for authorized administrators to assign and update user roles.

### 📝 Prompt Management
- **Full CRUD Support:** Create, view, edit, and delete prompts seamlessly.
- **Categorization & Tagging:** Organize prompts by domain (e.g., Coding, Research, Writing) and custom tags for easy discovery.
- **Visibility Controls:** Toggle prompts between **Public** (visible to all) and **Private** (visible only to the owner).
- **System Prompts:** Managed by the system "Bot" to provide baseline high-quality prompts for all users.

### ⚡ Interactive Prompt Runner
- **Variable Injection:** Use `{{variable_name}}` syntax within prompts to create reusable templates.
- **Dynamic Inputs:** Automatically generates input fields for any variables detected in a prompt.
- **Live Preview:** View how the prompt will look with provided variables before execution.
- **Streaming Output:** (Supported in server-enabled environments) Provides a real-time, typewriter-style experience for AI responses.

### 🎨 User Experience
- **Adaptive UI:** Fully responsive design optimized for desktop, tablet, and mobile devices.
- **Theming:** Support for both **Light** and **Dark** modes to reduce eye strain.
- **Responsive Design:** A modern, mobile-first interface with intuitive navigation.

## 🛠️ Tech Stack

### Frontend
- **HTML5 / CSS3 (Custom Styles):** Modern, adaptive styling with CSS variables for easy theming.
- **Vanilla JavaScript:** High-performance, client-side logic and DOM manipulation.
- **Supabase JS SDK:** Direct client-side interaction with Supabase Auth and Realtime features.
- **Tabler Icons:** For a clean and consistent iconography.

### Backend
- **FastAPI (Python):** A high-performance, asynchronous web framework for the API layer.
- **Supabase Python SDK:** Robust backend interaction with the Supabase PostgreSQL database.
- **Uvicorn:** High-performance ASGI server to run the FastAPI application.
- **Ngrok:** Used for secure tunneling to expose the local backend for testing and frontend integration.

### Database & Infrastructure
- **Supabase (PostgreSQL):** Relational database with Row-Level Security (RLS) for strict data isolation.
- **Row-Level Security (RLS):** Ensures users can only access their own prompts and profiles, while admins can manage the system.
- **Database Triggers:** Automates profile creation upon new user authentication.

## 🏗️ Architecture

The application follows a modern client-server architecture:

1. **Frontend (Client):** Hosted on GitHub Pages, the frontend communicates with the backend via RESTful API calls. It handles user interaction, session management via Supabase Auth, and the prompt execution UI.
2. **Backend (Server):** A FastAPI server acts as the intermediary, enforcing business logic, performing administrative tasks, and communicating securely with the database using a `service_role` key to bypass RLS for management operations.
3. **Supabase (Database & Auth):** Serves as the single source of truth for user identity, profile data, and the prompt repository, providing secure storage and automatic trigger-based automation.

## ⚙️ Setup & Installation

### Prerequisites
- Python 3.9+
- Supabase Account & Project
- Ngrok (for local development/exposure)

### Local Development

1. **Database Setup:**
   Run the provided SQL scripts in your Supabase SQL Editor in the following order:
   - `backend/schema.sql`
   - `backend/seed.sql`
   - `backend/update_prompts.sql`

2. **Environment Configuration:**
   Create a `.env` file in the `backend/` directory:
   ```env
   SUPABASE_URL=your_supabase_url
   SUPABASE_SERVICE_KEY=your_service_role_key
   SUPABASE_ANON_KEY=your_anon_key
   SYSTEM_USER_ID=the_id_of_your_bot_user
   NON_STREAM_TIMEOUT_SEC=120
   ```

3. **Run Backend:**
   ```bash
   cd backend
   pip install -r requirements.txt  # (If applicable)
   uvicorn app:app --reload
   ```

4. **Expose Backend:**
   Use ngrok to expose your local FastAPI server:
   ```bash
   ngrok http 8000
   ```
   Copy the ngrok URL and update the `API_BASE` in `frontend/index.html`.

5. **Run Frontend:**
   Open `frontend/index.html` in your browser or serve it via a local web server.

---
*Built with ❤️ for researchers and prompt engineers.*
