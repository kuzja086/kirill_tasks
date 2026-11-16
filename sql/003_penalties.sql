-- Штрафы: заявки, которые списывают баллы только после подтверждения.
-- Применение: psql ... -f sql/003_penalties.sql (или python tools/db_migrate.py)

CREATE TABLE IF NOT EXISTS penalties (
    id          bigserial   PRIMARY KEY,
    user_id     text        NOT NULL,
    points      integer     NOT NULL CHECK (points > 0),
    comment     text        NOT NULL CHECK (length(btrim(comment)) > 0),
    source      text        NOT NULL CHECK (source IN ('alice', 'admin')),
    status      text        NOT NULL DEFAULT 'awaiting_confirmation'
                            CHECK (status IN ('awaiting_confirmation', 'applied', 'rejected')),
    created_at  timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    resolved_by text,
    ledger_id   bigint      REFERENCES points_ledger (id)
);

COMMENT ON TABLE penalties IS
    'Заявки на штраф: баллы списываются только при подтверждении взрослым';
COMMENT ON COLUMN penalties.points IS 'Положительная сумма штрафа; в журнал пишется со знаком минус';
COMMENT ON COLUMN penalties.source IS 'alice — сказано голосом, admin — добавлено в админке';

CREATE INDEX IF NOT EXISTS penalties_user_status_idx ON penalties (user_id, status);
CREATE INDEX IF NOT EXISTS penalties_created_idx ON penalties (created_at DESC);

-- Причина операции для истории начислений и списаний.
ALTER TABLE points_ledger ADD COLUMN IF NOT EXISTS comment text;

-- Новая причина penalty в журнале (ограничение из 001_init.sql пересоздаём).
ALTER TABLE points_ledger DROP CONSTRAINT IF EXISTS points_ledger_reason_check;
ALTER TABLE points_ledger ADD CONSTRAINT points_ledger_reason_check
    CHECK (reason IN ('task_done', 'task_missed', 'reward_redeem', 'reward_refund', 'manual', 'penalty'));
