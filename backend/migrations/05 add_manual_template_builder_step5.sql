-- Step 5: Store LLM styling decisions for manual template photocards

ALTER TABLE post_image_generations
    ADD COLUMN IF NOT EXISTS llm_instructions JSONB NOT NULL DEFAULT '{}'::jsonb;
