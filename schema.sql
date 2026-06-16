-- ══════════════════════════════════════════════════════════════════════
-- Prompt DB — Schema (run in Supabase SQL Editor)
-- ══════════════════════════════════════════════════════════════════════

-- Cleanup existing triggers
drop trigger if exists on_auth_user_created on auth.users;
drop trigger if exists on_prompt_insert_set_public on prompts;

-- ── Profiles table (role-based system) ──────────────────────────────
create table profiles (
  id uuid primary key references auth.users on delete cascade,
  username text unique not null,
  email text not null,
  role text not null default 'Pending'
    check (role in ('Professor', 'Lab-Admin', 'MS', 'Project-Staff', 'Undergrad', 'Interns', 'Pending', 'Bot', 'Server-Admin')),
  created_at timestamptz default now()
);

alter table profiles enable row level security;

-- Users can read their own profile
create policy "Users can read own profile"
  on profiles for select
  using (auth.uid() = id);

-- Users can update their own profile (e.g. username)
create policy "Users can update own profile"
  on profiles for update
  using (auth.uid() = id)
  with check (auth.uid() = id);

-- Allow inserts from the trigger (runs as postgres/service role)
create policy "Service role can insert profiles"
  on profiles for insert
  with check (true);

-- ── Prompts table ───────────────────────────────────────────────────
create table prompts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users not null,
  title text not null,
  category text not null,
  prompt text not null,
  tags text[] default '{}',
  is_public boolean default false,
  created_at timestamptz default now()
);

alter table prompts enable row level security;

-- Select policy: visible if public OR owned by user OR belongs to a Bot
create policy "Prompts are viewable by everyone if public"
  on prompts for select
  using (is_public = true);

create policy "Users can view their own prompts"
  on prompts for select
  using (auth.uid() = user_id);

create policy "System prompts are viewable by everyone"
  on prompts for select
  using (
    exists (
      select 1 from profiles 
      where profiles.id = prompts.user_id 
      and profiles.role = 'Bot'
    )
  );

-- Insert/Update/Delete policy: only owner
create policy "Users can insert their own prompts"
  on prompts for insert
  with check (auth.uid() = user_id);

create policy "Users can update their own prompts"
  on prompts for update
  using (auth.uid() = user_id);

create policy "Users can delete their own prompts"
  on prompts for delete
  using (auth.uid() = user_id);

-- ── Automation Triggers ────────────────────────────────────────────

-- Trigger: Auto-create profile on signup
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.profiles (id, username, email, role)
  values (
     new.id,
     coalesce(new.raw_user_meta_data->>'username', split_part(new.email, '@', 1)),
     new.email,
     coalesce(new.raw_user_meta_data->>'role', 'Pending')
   );
  return new;
end;
$$;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

