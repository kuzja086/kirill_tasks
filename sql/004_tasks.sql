-- Дополнительные задачи: kind = 'optional'.
-- Применение: python tools/db_migrate.py (или psql -f sql/004_tasks.sql)
--
-- Дополнительная задача доступна каждый день, но не попадает в план и не
-- штрафуется: ребёнок берёт её сам, баллы начисляются после подтверждения.

ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_kind_check;
ALTER TABLE tasks
    ADD CONSTRAINT tasks_kind_check
    CHECK (kind IN ('daily', 'random', 'optional'));

-- Выборки справочника идут по паре (kind, is_active).
CREATE INDEX IF NOT EXISTS tasks_kind_active_idx ON tasks (kind, is_active);

COMMENT ON COLUMN tasks.kind IS
    'daily — каждый день; random — выборка из пула; optional — дополнительная, без штрафа';
COMMENT ON COLUMN tasks.is_active IS
    'false — скрыта: не попадает ни в план, ни в список дополнительных задач';
