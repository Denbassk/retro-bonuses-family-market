-- =====================================================================
-- 2026-09-11. Выполнить ОДИН раз в Supabase -> SQL Editor. Повторный запуск безопасен.
-- 1) retro_adjustments - ручные доплаты/вычеты ПОВЕРХ расчёта (пересчёт их больше не стирает)
-- 2) retro_calculation_details.adjustment_id - связь строки расчёта с доплатой
-- 3) store_opening_bonuses: плательщик = имя строки Excel (у составной строки нет одного поставщика),
--    дата оплаты, ключ (excel_name, store_label, year)
-- =====================================================================

-- ---------- 1. retro_adjustments ----------
CREATE TABLE IF NOT EXISTS public.retro_adjustments (
  id                      uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  supplier_id             uuid NOT NULL REFERENCES public.suppliers(id),
  supplier_brand_id       uuid REFERENCES public.supplier_brands(id),
  period_label            text NOT NULL CHECK (period_label ~ '^\d{4}-\d{2}$'),
  amount                  numeric(14,2) NOT NULL CHECK (amount <> 0),      -- минус = вычет
  bonus_form              text NOT NULL DEFAULT 'price_correction'
                          CHECK (bonus_form IN ('price_correction', 'marketing_service', 'cash')),
  notes                   text NOT NULL CHECK (btrim(notes) <> ''),
  source                  text NOT NULL DEFAULT 'admin'
                          CHECK (source IN ('admin', 'migration', 'excel_note', 'script')),
  migrated_from_detail_id uuid UNIQUE,                                     -- защита от двойного переноса
  created_at              timestamptz NOT NULL DEFAULT now(),
  created_by              text
);
CREATE INDEX IF NOT EXISTS retro_adjustments_sup_per_idx
  ON public.retro_adjustments (supplier_id, period_label);

ALTER TABLE public.retro_adjustments ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS retro_adjustments_admin_all ON public.retro_adjustments;
CREATE POLICY retro_adjustments_admin_all ON public.retro_adjustments
  FOR ALL TO authenticated USING (true) WITH CHECK (true);   -- админка работает под логином

-- ---------- 2. связь строки расчёта с доплатой ----------
ALTER TABLE public.retro_calculation_details
  ADD COLUMN IF NOT EXISTS adjustment_id uuid REFERENCES public.retro_adjustments(id);
CREATE INDEX IF NOT EXISTS retro_calc_details_adjustment_idx
  ON public.retro_calculation_details (adjustment_id);

-- ---------- 3. store_opening_bonuses ----------
ALTER TABLE public.store_opening_bonuses ADD COLUMN IF NOT EXISTS excel_name   text;
ALTER TABLE public.store_opening_bonuses ADD COLUMN IF NOT EXISTS payment_date date;

-- 8 строк, записанных 11.09 без excel_name, удаляются и перезаливаются скриптом с новым ключом
-- (иначе upsert по новому ключу их не узнает и задвоит). Других строк в таблице не было.
DELETE FROM public.store_opening_bonuses WHERE excel_name IS NULL;
ALTER TABLE public.store_opening_bonuses ALTER COLUMN excel_name SET NOT NULL;

-- старый ключ (supplier_id, store_label, year) снимаем: у составной строки supplier_id пустой
DO $$
DECLARE c text;
BEGIN
  FOR c IN SELECT conname FROM pg_constraint
           WHERE conrelid = 'public.store_opening_bonuses'::regclass AND contype = 'u' LOOP
    EXECUTE format('ALTER TABLE public.store_opening_bonuses DROP CONSTRAINT %I', c);
  END LOOP;
  FOR c IN SELECT indexname FROM pg_indexes
           WHERE schemaname = 'public' AND tablename = 'store_opening_bonuses'
             AND indexdef ILIKE 'CREATE UNIQUE INDEX%' AND indexname NOT LIKE '%pkey' LOOP
    EXECUTE format('DROP INDEX public.%I', c);
  END LOOP;
END $$;

ALTER TABLE public.store_opening_bonuses
  ADD CONSTRAINT store_opening_bonuses_excel_store_year_key UNIQUE (excel_name, store_label, year);

-- ---------- проверка ----------
SELECT table_name, column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'public'
  AND (table_name = 'retro_adjustments'
       OR (table_name = 'retro_calculation_details' AND column_name = 'adjustment_id')
       OR (table_name = 'store_opening_bonuses' AND column_name IN ('excel_name', 'payment_date')))
ORDER BY table_name, ordinal_position;
