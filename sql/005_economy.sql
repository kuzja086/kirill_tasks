-- Экономика в целых баллах: задача 1–10, план дня ≈ 13, награда ≈ за неделю.
--
-- tools/db_migrate.py прогоняет все файлы при каждом запуске, поэтому UPDATE
-- срабатывает только для «старой» цены: если родитель изменил стоимость
-- в админке, повторный запуск миграции её не перезапишет.

-- Задачи: старая шкала (5–15) → новая (1–2).
UPDATE tasks
   SET points = CASE title
                    WHEN 'Зарядка' THEN 2
                    WHEN 'Заправить кровать' THEN 1
                    WHEN 'Почистить зубы утром' THEN 1
                    WHEN 'Почистить зубы вечером' THEN 1
                    WHEN 'Прочитать 20 минут' THEN 2
                    WHEN 'Убрать игрушки' THEN 2
                    WHEN 'Помыть посуду' THEN 1
                    WHEN 'Помочь с готовкой' THEN 2
                    WHEN 'Выучить пять слов' THEN 1
                    WHEN 'Погулять 30 минут' THEN 2
                    WHEN 'Нарисовать рисунок' THEN 1
                    WHEN 'Сделать поделку' THEN 2
                    WHEN 'Помочь младшему' THEN 1
                    ELSE points
                END
 WHERE (title, points) IN (VALUES
            ('Зарядка', 10),
            ('Заправить кровать', 5),
            ('Почистить зубы утром', 5),
            ('Почистить зубы вечером', 5),
            ('Прочитать 20 минут', 15),
            ('Убрать игрушки', 10),
            ('Помыть посуду', 10),
            ('Помочь с готовкой', 15),
            ('Выучить пять слов', 15),
            ('Погулять 30 минут', 15),
            ('Нарисовать рисунок', 10),
            ('Сделать поделку', 15),
            ('Помочь младшему', 10)
        );

-- Награды: старая шкала (200–2500) → новая (10–200).
UPDATE rewards
   SET cost = CASE title
                  WHEN 'Наклейка' THEN 10
                  WHEN 'Мороженое' THEN 25
                  WHEN 'Час мультиков' THEN 40
                  WHEN 'Настольная игра' THEN 70
                  WHEN 'Поход в кино' THEN 100
                  WHEN 'Новый конструктор' THEN 200
                  ELSE cost
              END
 WHERE (title, cost) IN (VALUES
            ('Наклейка', 200),
            ('Мороженое', 350),
            ('Час мультиков', 500),
            ('Настольная игра', 970),
            ('Поход в кино', 1100),
            ('Новый конструктор', 2500)
        );

-- Свои задачи родителя могли остаться в старой шкале: приводим к 1–10,
-- иначе ограничение ниже не навесится.
UPDATE tasks SET points = 10 WHERE points > 10;
UPDATE tasks SET points = 1 WHERE points < 1;

ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_points_check;
ALTER TABLE tasks ADD CONSTRAINT tasks_points_check CHECK (points BETWEEN 1 AND 10);

-- Незавершённые назначения переводим на новую шкалу. Иначе ребёнок увидит
-- «85 баллов» за сегодняшний день, а штраф за вчерашние pending-задачи
-- спишет сразу 80 — это несопоставимо с новой экономикой.
-- Подтверждённые (done) и пропущенные (missed) дни не трогаем: журнал
-- и история неизменяемы, старые начисления остаются как есть.
UPDATE daily_assignments AS d
   SET points = t.points
  FROM tasks AS t
 WHERE d.task_id = t.id
   AND d.status IN ('pending', 'awaiting_confirmation')
   AND d.points <> t.points;

UPDATE daily_assignments SET points = 10 WHERE status IN ('pending', 'awaiting_confirmation') AND points > 10;
UPDATE daily_assignments SET points = 1 WHERE status IN ('pending', 'awaiting_confirmation') AND points < 1;

COMMENT ON COLUMN tasks.points IS 'Баллы за задачу, целое 1–10 (план дня ≈ 13)';
COMMENT ON COLUMN rewards.cost IS 'Стоимость награды в баллах: ≈ 70 — награда за неделю';
