-- Баланс не может быть меньше нуля: штрафы и пропущенные задачи списывают
-- только накопленное. Здесь — колонка «сколько реально списано» и разовая
-- нормализация уже существующих отрицательных балансов.
--
-- Миграция идемпотентна: ADD COLUMN IF NOT EXISTS, backfill только для
-- незаполненных значений, компенсация — только пока сумма отрицательная.

ALTER TABLE penalties
    ADD COLUMN IF NOT EXISTS charged_points integer;

COMMENT ON COLUMN penalties.charged_points IS
    'Сколько баллов реально списано: не больше остатка, баланс не уходит в минус';

-- Для уже применённых штрафов фактическое списание видно в журнале.
UPDATE penalties AS p
   SET charged_points = -l.delta
  FROM points_ledger AS l
 WHERE p.ledger_id = l.id
   AND p.status = 'applied'
   AND p.charged_points IS NULL
   AND l.delta < 0;

-- Разовая нормализация: если ребёнок уже ушёл в минус по старым правилам,
-- возвращаем баланс к нулю компенсирующей записью. Журнал не переписываем.
INSERT INTO points_ledger (user_id, delta, reason, comment)
SELECT balance.user_id, -balance.amount, 'manual',
       'Баланс приведён к нулю: баллы не могут быть меньше 0'
  FROM (
        SELECT user_id, SUM(delta) AS amount
          FROM points_ledger
         GROUP BY user_id
       ) AS balance
 WHERE balance.amount < 0;
