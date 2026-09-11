-- ============================================================
-- ДИАГНОСТИКА: Поиск штрих-кодов Монжар в turnover_transactions
-- Сравниваем с выгрузкой поставщика за март 2026
-- Запустить в BigQuery Console: https://console.cloud.google.com/bigquery
-- Проект: family-market-analytics
-- ============================================================

-- ШАГ 1: Что вообще есть в turnover за март 2026 по ключевым словам Монжар
-- Ищем по самым уникальным частям названий из файла поставщика

SELECT
  t.barcode,
  t.product_name,
  ROUND(SUM(t.quantity), 0)       AS qty_mar,
  ROUND(SUM(t.check_amount), 2)   AS sum_mar,

  -- Определяем, к какой позиции поставщика относится товар
  CASE
    WHEN LOWER(t.product_name) LIKE '%джелоп%зуб%'      THEN 'Джелопі Зуби 600гр'
    WHEN LOWER(t.product_name) LIKE '%джелоп%серц%'     THEN 'Джелопі Серце 600гр'
    WHEN LOWER(t.product_name) LIKE '%джелоп%червяк%'   THEN 'Джелопі Червяки 600гр'
    WHEN LOWER(t.product_name) LIKE '%олівець%пірат%'   THEN 'Драже Олівець Пірати 22г'
    WHEN LOWER(t.product_name) LIKE '%тофі%тайм%'
      OR LOWER(t.product_name) LIKE '%tofitaim%'        THEN 'Жув. Цукерка Тофі Тайм Вишня 25г'
    WHEN LOWER(t.product_name) LIKE '%шокер%'           THEN 'Жув. Цукерка Шокер Малина-Персик'
    WHEN LOWER(t.product_name) LIKE '%кислиц%кавун%'
      OR LOWER(t.product_name) LIKE '%кислиця%кавун%'  THEN 'Жуйка Кислиця Кавун'
    WHEN LOWER(t.product_name) LIKE '%кислиц%полун%'
      OR LOWER(t.product_name) LIKE '%кислиця%полун%'  THEN 'Жуйка Кислиця Полуниця'
    WHEN LOWER(t.product_name) LIKE '%куул%фреш%'
      OR LOWER(t.product_name) LIKE '%cool%fresh%'      THEN 'Жуйка Куул Фреш Малина'
    WHEN LOWER(t.product_name) LIKE '%жуйка%турбо%'
      OR LOWER(t.product_name) LIKE '%turbo%'           THEN 'Жуйка Турбо'
    WHEN LOWER(t.product_name) LIKE '%кисло%спрей%'
      OR LOWER(t.product_name) LIKE '%кисло-спрей%'    THEN 'Кисло-Спрей 25г'
    WHEN LOWER(t.product_name) LIKE '%льодяник%паличц%'
      OR LOWER(t.product_name) LIKE '%кисла%п%ятка%'
      OR LOWER(t.product_name) LIKE '%кисла п%'        THEN 'Льодяник Кисла П*ятка 9гр'
    WHEN LOWER(t.product_name) LIKE '%lico%rico%'
      OR LOWER(t.product_name) LIKE '%ліко%ріко%'      THEN 'Мармеладна Палочка Lico Rico Mix'
    WHEN LOWER(t.product_name) LIKE '%мармелад%стрічк%'
      OR LOWER(t.product_name) LIKE '%мармел%стрічк%'  THEN 'Мармеладна Стрічка Мікс 15гр'
    WHEN LOWER(t.product_name) LIKE '%машинк%сюрприз%'
      OR LOWER(t.product_name) LIKE '%форсаж%'         THEN 'Машинка-Сюрприз Форсаж'
    WHEN LOWER(t.product_name) LIKE '%шприц%джем%'
      OR LOWER(t.product_name) LIKE '%солодк%шприц%'   THEN 'Солодкий Шприц з Джемом'
    WHEN LOWER(t.product_name) LIKE '%той джой%'
      OR LOWER(t.product_name) LIKE '%3d%желейн%'
      OR LOWER(t.product_name) LIKE '%желейне%ок%'     THEN 'Той Джой 3D Желейне ОКО 18г'
    WHEN LOWER(t.product_name) LIKE '%юмі%джелі%ведмед%'
      OR LOWER(t.product_name) LIKE '%yumi%jelly%bear%' THEN 'Цукерка Юмі Джелі Ведмедики 70г'
    WHEN LOWER(t.product_name) LIKE '%юмі%джелі%кола%'  THEN 'Цукерка Юмі Джелі Кола 70г'
    WHEN LOWER(t.product_name) LIKE '%юмі%джелі%фрукт%' THEN 'Цукерка Юмі Джелі Фрукти 70г'
    WHEN LOWER(t.product_name) LIKE '%цуценя%сюрприз%'
      OR LOWER(t.product_name) LIKE '%зоо%планет%цуцен%' THEN 'Цуценя-Сюрприз Зоо-Планета'
    WHEN LOWER(t.product_name) LIKE '%чарівн%ліхтарик%'
      OR LOWER(t.product_name) LIKE '%ліхтарик%'       THEN 'Чарівний Ліхтарик 1г'
    WHEN LOWER(t.product_name) LIKE '%барбелл%'         THEN 'Яйце з Сюрпризом Барбелла'
    WHEN LOWER(t.product_name) LIKE '%яйц%зоо%планет%'  THEN 'Яйце з Сюрпризом Зоо Планета'
    ELSE '❓ НЕ ОПРЕДЕЛЕНО'
  END AS supplier_product

FROM `family-market-analytics.family_market.turnover_transactions` t
WHERE
  DATE(t.transaction_datetime) >= '2026-03-01'
  AND DATE(t.transaction_datetime) <  '2026-04-01'
  AND (
    -- Джелопі
    LOWER(t.product_name) LIKE '%джелоп%'
    -- Драже Олівець
    OR LOWER(t.product_name) LIKE '%олівець%'
    OR LOWER(t.product_name) LIKE '%оливець%'
    -- Тофі Тайм
    OR LOWER(t.product_name) LIKE '%тофі%'
    OR LOWER(t.product_name) LIKE '%tofi%'
    -- Шокер
    OR LOWER(t.product_name) LIKE '%шокер%'
    -- Кислиця
    OR LOWER(t.product_name) LIKE '%кислиц%'
    -- Куул Фреш
    OR LOWER(t.product_name) LIKE '%куул%'
    OR LOWER(t.product_name) LIKE '%cool%fresh%'
    -- Турбо
    OR (LOWER(t.product_name) LIKE '%жуйка%' AND LOWER(t.product_name) LIKE '%турбо%')
    -- Кисло-Спрей
    OR LOWER(t.product_name) LIKE '%кисло%спрей%'
    -- Льодяник / Кисла П*ятка
    OR LOWER(t.product_name) LIKE '%кисла%п%ятка%'
    OR (LOWER(t.product_name) LIKE '%льодяник%' AND LOWER(t.product_name) LIKE '%палич%')
    -- Lico Rico
    OR LOWER(t.product_name) LIKE '%lico%'
    OR LOWER(t.product_name) LIKE '%ліко%'
    -- Мармеладна Стрічка
    OR (LOWER(t.product_name) LIKE '%мармелад%' AND LOWER(t.product_name) LIKE '%стрічк%')
    -- Машинка Форсаж
    OR LOWER(t.product_name) LIKE '%форсаж%'
    OR (LOWER(t.product_name) LIKE '%машинк%' AND LOWER(t.product_name) LIKE '%сюрприз%')
    -- Шприц з Джемом
    OR LOWER(t.product_name) LIKE '%шприц%'
    -- Той Джой
    OR LOWER(t.product_name) LIKE '%той%джой%'
    OR LOWER(t.product_name) LIKE '%toy%joy%'
    -- Юмі Джелі
    OR LOWER(t.product_name) LIKE '%юмі%'
    OR LOWER(t.product_name) LIKE '%yumi%'
    -- Цуценя Зоо-Планета
    OR LOWER(t.product_name) LIKE '%цуценя%'
    -- Чарівний Ліхтарик
    OR LOWER(t.product_name) LIKE '%ліхтарик%'
    -- Барбелла / Зоо Планета яйце
    OR LOWER(t.product_name) LIKE '%барбел%'
    OR (LOWER(t.product_name) LIKE '%яйц%' AND LOWER(t.product_name) LIKE '%зоо%')
  )
GROUP BY t.barcode, t.product_name
ORDER BY supplier_product, sum_mar DESC;


-- ============================================================
-- ШАГ 2: ИТОГОВОЕ СРАВНЕНИЕ — BQ vs Поставщик
-- После того как ШАГ 1 даст штрих-коды, сравниваем суммы
-- ============================================================

-- Данные поставщика для сверки (из файла "Продажи Монжар март 26.xlsx")
WITH supplier_data AS (
  SELECT * FROM UNNEST([
    STRUCT('Джелопі Зуби 600гр'              AS name, 1216 AS qty, 2883.48 AS revenue),
    STRUCT('Джелопі Серце 600гр'             AS name, 1007 AS qty, 2465.50 AS revenue),
    STRUCT('Джелопі Червяки 600гр'           AS name, 1877 AS qty, 4205.49 AS revenue),
    STRUCT('Драже Олівець Пірати 22г'        AS name,   25 AS qty,  350.01 AS revenue),
    STRUCT('Жув. Цукерка Тофі Тайм Вишня 25г' AS name,  3 AS qty,   28.50 AS revenue),
    STRUCT('Жув. Цукерка Шокер Малина-Персик' AS name, 418 AS qty, 3205.00 AS revenue),
    STRUCT('Жуйка Кислиця Кавун'             AS name,  960 AS qty, 1920.00 AS revenue),
    STRUCT('Жуйка Кислиця Полуниця'          AS name, 1124 AS qty, 2351.45 AS revenue),
    STRUCT('Жуйка Куул Фреш Малина'          AS name,  911 AS qty, 1822.00 AS revenue),
    STRUCT('Жуйка Турбо'                     AS name, 3078 AS qty, 7694.95 AS revenue),
    STRUCT('Кисло-Спрей 25г'                 AS name,  122 AS qty, 1829.99 AS revenue),
    STRUCT('Льодяник Кисла П*ятка 9гр'       AS name, 1260 AS qty,10207.40 AS revenue),
    STRUCT('Мармеладна Палочка Lico Rico Mix' AS name, 1647 AS qty, 4941.03 AS revenue),
    STRUCT('Мармеладна Стрічка Мікс 15гр'    AS name, 1005 AS qty, 7694.00 AS revenue),
    STRUCT('Машинка-Сюрприз Форсаж'          AS name,  257 AS qty, 7709.98 AS revenue),
    STRUCT('Солодкий Шприц з Джемом'         AS name,  152 AS qty, 1215.99 AS revenue),
    STRUCT('Той Джой 3D Желейне ОКО 18г'     AS name,   24 AS qty,  576.00 AS revenue),
    STRUCT('Цукерка Юмі Джелі Ведмедики 70г' AS name,  181 AS qty, 3739.67 AS revenue),
    STRUCT('Цукерка Юмі Джелі Кола 70г'      AS name,  177 AS qty, 3699.06 AS revenue),
    STRUCT('Цукерка Юмі Джелі Фрукти 70г'    AS name,  174 AS qty, 3571.05 AS revenue),
    STRUCT('Цуценя-Сюрприз Зоо-Планета'      AS name,  292 AS qty, 8759.97 AS revenue),
    STRUCT('Чарівний Ліхтарик 1г'            AS name,   44 AS qty,  660.00 AS revenue),
    STRUCT('Яйце з Сюрпризом Барбелла'       AS name,   10 AS qty,  120.00 AS revenue),
    STRUCT('Яйце з Сюрпризом Зоо Планета'    AS name,   76 AS qty, 1520.02 AS revenue)
  ])
),

-- Данные из BQ (агрегация по группе товара)
bq_data AS (
  SELECT
    CASE
      WHEN LOWER(t.product_name) LIKE '%джелоп%зуб%'      THEN 'Джелопі Зуби 600гр'
      WHEN LOWER(t.product_name) LIKE '%джелоп%серц%'     THEN 'Джелопі Серце 600гр'
      WHEN LOWER(t.product_name) LIKE '%джелоп%червяк%'   THEN 'Джелопі Червяки 600гр'
      WHEN LOWER(t.product_name) LIKE '%олівець%пірат%'   THEN 'Драже Олівець Пірати 22г'
      WHEN LOWER(t.product_name) LIKE '%тофі%тайм%'       THEN 'Жув. Цукерка Тофі Тайм Вишня 25г'
      WHEN LOWER(t.product_name) LIKE '%шокер%'           THEN 'Жув. Цукерка Шокер Малина-Персик'
      WHEN LOWER(t.product_name) LIKE '%кислиц%кавун%'
        OR LOWER(t.product_name) LIKE '%кислиця%кавун%'  THEN 'Жуйка Кислиця Кавун'
      WHEN LOWER(t.product_name) LIKE '%кислиц%полун%'
        OR LOWER(t.product_name) LIKE '%кислиця%полун%'  THEN 'Жуйка Кислиця Полуниця'
      WHEN LOWER(t.product_name) LIKE '%куул%фреш%'       THEN 'Жуйка Куул Фреш Малина'
      WHEN LOWER(t.product_name) LIKE '%жуйка%турбо%'     THEN 'Жуйка Турбо'
      WHEN LOWER(t.product_name) LIKE '%кисло%спрей%'     THEN 'Кисло-Спрей 25г'
      WHEN LOWER(t.product_name) LIKE '%кисла%п%ятка%'
        OR (LOWER(t.product_name) LIKE '%льодяник%' AND LOWER(t.product_name) LIKE '%палич%')
                                                           THEN 'Льодяник Кисла П*ятка 9гр'
      WHEN LOWER(t.product_name) LIKE '%lico%'
        OR LOWER(t.product_name) LIKE '%ліко%'            THEN 'Мармеладна Палочка Lico Rico Mix'
      WHEN LOWER(t.product_name) LIKE '%мармелад%стрічк%' THEN 'Мармеладна Стрічка Мікс 15гр'
      WHEN LOWER(t.product_name) LIKE '%форсаж%'
        OR (LOWER(t.product_name) LIKE '%машинк%' AND LOWER(t.product_name) LIKE '%сюрприз%')
                                                           THEN 'Машинка-Сюрприз Форсаж'
      WHEN LOWER(t.product_name) LIKE '%шприц%'           THEN 'Солодкий Шприц з Джемом'
      WHEN LOWER(t.product_name) LIKE '%той%джой%'
        OR LOWER(t.product_name) LIKE '%toy%joy%'         THEN 'Той Джой 3D Желейне ОКО 18г'
      WHEN LOWER(t.product_name) LIKE '%юмі%' AND LOWER(t.product_name) LIKE '%ведмед%'
                                                           THEN 'Цукерка Юмі Джелі Ведмедики 70г'
      WHEN LOWER(t.product_name) LIKE '%юмі%' AND LOWER(t.product_name) LIKE '%кола%'
                                                           THEN 'Цукерка Юмі Джелі Кола 70г'
      WHEN LOWER(t.product_name) LIKE '%юмі%' AND LOWER(t.product_name) LIKE '%фрукт%'
                                                           THEN 'Цукерка Юмі Джелі Фрукти 70г'
      WHEN LOWER(t.product_name) LIKE '%цуценя%'          THEN 'Цуценя-Сюрприз Зоо-Планета'
      WHEN LOWER(t.product_name) LIKE '%ліхтарик%'        THEN 'Чарівний Ліхтарик 1г'
      WHEN LOWER(t.product_name) LIKE '%барбел%'          THEN 'Яйце з Сюрпризом Барбелла'
      WHEN LOWER(t.product_name) LIKE '%яйц%' AND LOWER(t.product_name) LIKE '%зоо%'
                                                           THEN 'Яйце з Сюрпризом Зоо Планета'
      ELSE NULL
    END AS matched_name,
    ROUND(SUM(t.quantity), 0)      AS bq_qty,
    ROUND(SUM(t.check_amount), 2)  AS bq_revenue,
    COUNT(DISTINCT t.barcode)      AS barcode_count,
    STRING_AGG(DISTINCT t.barcode ORDER BY t.barcode) AS barcodes
  FROM `family-market-analytics.family_market.turnover_transactions` t
  WHERE
    DATE(t.transaction_datetime) >= '2026-03-01'
    AND DATE(t.transaction_datetime) <  '2026-04-01'
    AND (
      LOWER(t.product_name) LIKE '%джелоп%'
      OR LOWER(t.product_name) LIKE '%олівець%пірат%'
      OR LOWER(t.product_name) LIKE '%тофі%тайм%'
      OR LOWER(t.product_name) LIKE '%шокер%'
      OR LOWER(t.product_name) LIKE '%кислиц%'
      OR LOWER(t.product_name) LIKE '%куул%фреш%'
      OR (LOWER(t.product_name) LIKE '%жуйка%' AND LOWER(t.product_name) LIKE '%турбо%')
      OR LOWER(t.product_name) LIKE '%кисло%спрей%'
      OR LOWER(t.product_name) LIKE '%кисла%п%ятка%'
      OR (LOWER(t.product_name) LIKE '%льодяник%' AND LOWER(t.product_name) LIKE '%палич%')
      OR LOWER(t.product_name) LIKE '%lico%'
      OR (LOWER(t.product_name) LIKE '%мармелад%' AND LOWER(t.product_name) LIKE '%стрічк%')
      OR LOWER(t.product_name) LIKE '%форсаж%'
      OR (LOWER(t.product_name) LIKE '%машинк%' AND LOWER(t.product_name) LIKE '%сюрприз%')
      OR LOWER(t.product_name) LIKE '%шприц%джем%'
      OR LOWER(t.product_name) LIKE '%той%джой%'
      OR LOWER(t.product_name) LIKE '%toy%joy%'
      OR LOWER(t.product_name) LIKE '%юмі%'
      OR LOWER(t.product_name) LIKE '%yumi%'
      OR LOWER(t.product_name) LIKE '%цуценя%'
      OR LOWER(t.product_name) LIKE '%ліхтарик%'
      OR LOWER(t.product_name) LIKE '%барбел%'
      OR (LOWER(t.product_name) LIKE '%яйц%' AND LOWER(t.product_name) LIKE '%зоо%')
    )
  GROUP BY matched_name
  HAVING matched_name IS NOT NULL
)

SELECT
  s.name                               AS supplier_name,
  b.barcodes                           AS bq_barcodes,
  b.barcode_count                      AS bc_count,
  s.qty                                AS supplier_qty,
  b.bq_qty                             AS bq_qty,
  COALESCE(b.bq_qty, 0) - s.qty       AS qty_diff,
  s.revenue                            AS supplier_revenue,
  b.bq_revenue                         AS bq_revenue,
  ROUND(COALESCE(b.bq_revenue, 0) - s.revenue, 2) AS revenue_diff,
  CASE
    WHEN b.matched_name IS NULL THEN '❌ НЕ НАЙДЕНО в BQ'
    WHEN ABS(COALESCE(b.bq_revenue, 0) - s.revenue) < 50 THEN '✅ Сходится'
    WHEN ABS(COALESCE(b.bq_revenue, 0) - s.revenue) < 500 THEN '⚠️ Расхождение'
    ELSE '🔴 Большое расхождение'
  END AS status
FROM supplier_data s
LEFT JOIN bq_data b ON s.name = b.matched_name
ORDER BY
  CASE WHEN b.matched_name IS NULL THEN 1 ELSE 0 END,
  ABS(COALESCE(b.bq_revenue, 0) - s.revenue) DESC;
