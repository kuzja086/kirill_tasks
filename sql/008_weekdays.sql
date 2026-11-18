-- Расписание задач по дням недели: weekdays = {1, 3} — только Пн и Ср,
-- NULL или пустой массив — каждый день.
--
-- Миграция идемпотентна: ADD COLUMN IF NOT EXISTS, DROP CONSTRAINT IF EXISTS.

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS weekdays smallint[];

COMMENT ON COLUMN tasks.weekdays IS
    'Дни недели (ISO: 1 = Пн ... 7 = Вс), когда задача попадает в план; NULL — каждый день';

ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_weekdays_check;
ALTER TABLE tasks ADD CONSTRAINT tasks_weekdays_check
    CHECK (weekdays IS NULL OR weekdays <@ ARRAY[1, 2, 3, 4, 5, 6, 7]::smallint[]);
