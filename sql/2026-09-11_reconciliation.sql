-- =====================================================================
-- 2026-09-11. ЭТАП 4: таблица результатов автосверки. Supabase -> SQL Editor. Повторный запуск безопасен.
-- Пишет только core\reconcile_facts.py (service key). Админка - только чтение.
-- =====================================================================
CREATE TABLE IF NOT EXISTS public.retro_reconciliation (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  supplier_id     uuid NOT NULL REFERENCES public.suppliers(id),
  period_label    text NOT NULL CHECK (period_label ~ '^\d{4}-\d{2}$'),
  group_key       text,                 -- составная строка Excel (БІР Кег + Славутич): статус общий на группу
  fact_amount     numeric(14,2),        -- retro_payments_fact; NULL = не заполнено (это НЕ 0)
  excel_amount    numeric(14,2),        -- ячейка Excel (для группы - общая)
  excel_cell      text,
  calc_amount     numeric(14,2),        -- retro_calculations.total_retro (с доплатами и фикс-бонусом)
  calc_status     text,
  calc_created_at timestamptz,
  data_loaded_at  timestamptz,          -- последняя загрузка данных BQ / выписки по паре
  delta           numeric(14,2),        -- факт - расчёт (для группы - по группе)
  delta_pct       numeric(9,4),
  status          text NOT NULL CHECK (status IN (
                    'MATCH', 'MINOR', 'MISMATCH', 'REDISTRIBUTION', 'MANUAL', 'STALE_CALC',
                    'PENDING', 'NOT_PAID', 'NOT_EXPECTED', 'EXCEL_ONLY',
                    'ZERO_OK', 'ZERO_BUT_CALC', 'FACT_NO_CALC', 'EXCLUDED_OWNER')),
  diagnosis       text,
  diagnosis_data  jsonb,
  run_id          uuid NOT NULL,
  checked_at      timestamptz NOT NULL DEFAULT now(),
  UNIQUE (supplier_id, period_label)
);
CREATE INDEX IF NOT EXISTS retro_reconciliation_status_idx ON public.retro_reconciliation (status, period_label);

ALTER TABLE public.retro_reconciliation ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS retro_reconciliation_read ON public.retro_reconciliation;
CREATE POLICY retro_reconciliation_read ON public.retro_reconciliation
  FOR SELECT TO authenticated USING (true);

SELECT column_name, data_type, is_nullable FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'retro_reconciliation' ORDER BY ordinal_position;
