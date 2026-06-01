-- Enable row-level security so users only see their own prompts
create table prompts (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users not null,
  title text not null,
  category text not null,
  prompt text not null,
  tags text[] default '{}',
  created_at timestamptz default now()
);

alter table prompts enable row level security;

create policy "Users can only access their own prompts"
  on prompts for all
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);