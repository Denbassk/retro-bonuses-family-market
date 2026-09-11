-- =====================================================================
-- 2026-09-11. Журнал загрузок Excel из админки (черновик -> подтверждение -> запись).
-- Supabase -> SQL Editor. Повторный запуск безопасен. Пишет только локальный сервер админки (service key).
-- =====================================================================
CREATE TABLE IF NOT EXISTS public.retro_fact_imports (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  file_name    text NOT NULL,                 -- имя файла, как его выбрал пользователь
  stored_path  text,                          -- куда сохранён в папке Ретро_Excel
  file_hash    text NOT NULL,                 -- sha256: тот же файл второй раз узнаётся
  status       text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'applied', 'cancelled', 'failed')),
  uploaded_by  text,
  uploaded_at  timestamptz NOT NULL DEFAULT now(),
  applied_by   text,
  applied_at   timestamptz,
  summary      jsonb,                         -- счётчики черновика и контрольные суммы
  applied      jsonb,                         -- что записано: ячейки фактов, конфликты, бонусы
  error        text
);
CREATE INDEX IF NOT EXISTS retro_fact_imports_hash_idx ON public.retro_fact_imports (file_hash, status);

ALTER TABLE public.retro_fact_imports ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS retro_fact_imports_read ON public.retro_fact_imports;
CREATE POLICY retro_fact_imports_read ON public.retro_fact_imports FOR SELECT TO authenticated USING (true);

SELECT column_name, data_type FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'retro_fact_imports' ORDER BY ordinal_position;
