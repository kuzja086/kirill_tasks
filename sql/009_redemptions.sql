-- Выдача наград: заявка requested → issued / cancelled, отмена возвращает баллы.
--
-- Миграция идемпотентна: ADD COLUMN IF NOT EXISTS, CREATE INDEX IF NOT EXISTS.

ALTER TABLE reward_redemptions
    ADD COLUMN IF NOT EXISTS resolved_at timestamptz,
    ADD COLUMN IF NOT EXISTS resolved_by text;

COMMENT ON COLUMN reward_redemptions.resolved_at IS
    'Когда взрослый выдал награду или отменил заявку';
COMMENT ON COLUMN reward_redemptions.resolved_by IS
    'Кто обработал заявку: admin (или другое имя)';

-- Один возврат на заявку: страховка от двойного начисления баллов.
CREATE UNIQUE INDEX IF NOT EXISTS points_ledger_redemption_reason_uniq
    ON points_ledger (reward_redemption_id, reason)
 WHERE reward_redemption_id IS NOT NULL;
