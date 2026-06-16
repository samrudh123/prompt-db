UPDATE prompts 
SET is_public = true 
WHERE user_id IN (SELECT id FROM profiles WHERE role = 'Bot');