-- Пропущенные задачи: штраф за них — такая же заявка, как штраф голосом.
-- Автоматически баллы больше не списываются: родитель подтверждает заявку,
-- и только тогда пишется списание (не больше остатка, баланс не ниже нуля).
--
-- Миграция идемпотентна: ADD COLUMN IF NOT EXISTS, DROP CONSTRAINT IF EXISTS.

ALTER TABLE penalties
    ADD COLUMN IF NOT EXISTS assignment_id bigint REFERENCES daily_assignments (id);

COMMENT ON COLUMN penalties.assignment_id IS
    'Пропущенная задача, за которую выставлена заявка (source = auto)';

ALTER TABLE penalties DROP CONSTRAINT IF EXISTS penalties_source_check;
ALTER TABLE penalties ADD CONSTRAINT penalties_source_check
    CHECK (source IN ('alice', 'admin', 'auto'));

COMMENT ON COLUMN penalties.source IS
    'alice — сказано голосом, admin — добавлено в админке, auto — пропущенная задача';

-- Одна заявка на одну пропущенную задачу: повторный запуск ленивого
-- создания штрафов не должен плодить дубликаты.
CREATE UNIQUE INDEX IF NOT EXISTS penalties_assignment_uniq
    ON penalties (assignment_id)
 WHERE assignment_id IS NOT NULL;
