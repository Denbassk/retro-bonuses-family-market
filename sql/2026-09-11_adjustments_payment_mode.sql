-- 2026-09-11: доплаты «не ретро» (ДМП, кубы, компенсации акций) - как они соотносятся с «Оплачено».
--
-- payment_mode:
--   in_payment - деньги пришли ВМЕСТЕ с ретро и сидят в «Оплачено» (кубы Якобз, компенсации акций Глобал-Сервіс),
--                либо это договорённость, меняющая начисление (Маршалл: порог 8 SKU, вычет опта IcePresso).
--                Прибавляется к «Начислено» (total_retro), чтобы факт и расчёт сравнивались честно. Так было всегда.
--   separate   - заплачено ОТДЕЛЬНО, в «Оплачено» не входит (ДМП Славутич). Только запись: «Начислено» не меняет,
--                на сверку факт/расчёт не влияет; при сравнении с Excel прибавляется к факту (в Excel сумма общая).
-- Существующие 9 доплат остаются in_payment (DEFAULT) - ничего не пересчитывается.

ALTER TABLE public.retro_adjustments
  ADD COLUMN IF NOT EXISTS payment_mode text NOT NULL DEFAULT 'in_payment';

ALTER TABLE public.retro_adjustments DROP CONSTRAINT IF EXISTS retro_adjustments_payment_mode_chk;
ALTER TABLE public.retro_adjustments
  ADD CONSTRAINT retro_adjustments_payment_mode_chk CHECK (payment_mode IN ('in_payment', 'separate'));

COMMENT ON COLUMN public.retro_adjustments.payment_mode IS
  'in_payment: входит в «Оплачено», прибавляется к total_retro; separate: заплачено отдельно, только запись';

-- проверка
SELECT payment_mode, COUNT(*), SUM(amount) FROM public.retro_adjustments GROUP BY 1;
