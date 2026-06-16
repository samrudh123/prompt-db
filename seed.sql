-- ══════════════════════════════════════════════════════════════════════
-- Prompt DB — Seed data (run in Supabase SQL Editor AFTER schema.sql)
-- ══════════════════════════════════════════════════════════════════════

-- ── Seed prompts ────────────────────────────────────────────────────
INSERT INTO prompts (id, user_id, title, category, prompt, tags, created_at)
VALUES 
  (gen_random_uuid(), '3b395ec1-9172-4e17-abc5-47f3e6bdb1ed', 'Summarise meeting notes', 'Summarisation', 'Summarise the following meeting notes into clear action items and key decisions:
  
{{meeting_notes}}', ARRAY['work','meetings'], NOW()),
  (gen_random_uuid(), '3b395ec1-9172-4e17-abc5-47f3e6bdb1ed', 'Write a professional email', 'Emails', 'Write a professional email to {{recipient}} about {{topic}}. Tone: {{tone}}. Keep it concise.', ARRAY['email','professional'], NOW()),
  (gen_random_uuid(), '3b395ec1-9172-4e17-abc5-47f3e6bdb1ed', 'Explain code snippet', 'Coding', 'Explain the following code in simple terms:
  
```
{{code}}
```', ARRAY['code','debug'], NOW()),
  (gen_random_uuid(), '3b395ec1-9172-4e17-abc5-47f3e6bdb1ed', 'Blog post outline', 'Writing', 'Create a detailed blog post outline for: "{{topic}}". Include intro, 5 sections with sub-points, and conclusion.', ARRAY['content','writing'], NOW()),
  (gen_random_uuid(), '3b395ec1-9172-4e17-abc5-47f3e6bdb1ed', 'Competitive analysis', 'Research', 'Brief competitive analysis of {{company}} vs top 3 competitors in {{market}}. Compare price, features, and positioning.', ARRAY['research','strategy'], NOW());

-- ── Seed profile for the system user ────────────────────────────────
-- Update the email below to match the actual email of your seed user.
INSERT INTO profiles (id, username, email, role)
VALUES (
  '3b395ec1-9172-4e17-abc5-47f3e6bdb1ed',
  'SIMHA',
  'discord-bot@prompt-db.com',
  'Bot'
)
ON CONFLICT (id) DO NOTHING