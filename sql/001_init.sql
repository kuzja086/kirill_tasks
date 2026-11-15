-- Схема навыка-мотиватора: задачи, дневной план, баллы и награды.
-- Применение: psql -h <хост> -U alice_skill -d alice_skill -f sql/001_init.sql

-- Справочник задач.
-- kind = 'daily'  — ежедневная, обязательная, попадает в план каждый день;
-- kind = 'random' — задача из пула, из которого каждый день берётся выборка.
CREATE TABLE IF NOT EXISTS tasks (
    id         bigserial PRIMARY KEY,
    title      text        NOT NULL,
    kind       text        NOT NULL CHECK (kind IN ('daily', 'random')),
    points     integer     NOT NULL CHECK (points > 0),
    is_active  boolean     NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS tasks_title_kind_uniq ON tasks (lower(title), kind);

-- Задача, назначенная ребёнку на конкретный день. Название и стоимость
-- копируются на момент планирования: правка справочника не переписывает историю.
CREATE TABLE IF NOT EXISTS daily_assignments (
    id          bigserial PRIMARY KEY,
    user_id     text        NOT NULL,
    plan_date   date        NOT NULL,
    task_id     bigint      NOT NULL REFERENCES tasks (id),
    title       text        NOT NULL,
    kind        text        NOT NULL,
    points      integer     NOT NULL,
    status      text        NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending', 'awaiting_confirmation', 'done', 'missed')),
    claimed_at  timestamptz,
    resolved_at timestamptz,
    UNIQUE (user_id, plan_date, task_id)
);

CREATE INDEX IF NOT EXISTS daily_assignments_user_date_idx
    ON daily_assignments (user_id, plan_date);

-- Журнал начислений и списаний. Баланс = SUM(delta) по пользователю.
CREATE TABLE IF NOT EXISTS points_ledger (
    id                   bigserial PRIMARY KEY,
    user_id              text        NOT NULL,
    delta                integer     NOT NULL,
    reason               text        NOT NULL
                                     CHECK (reason IN ('task_done', 'task_missed', 'reward_redeem', 'reward_refund', 'manual')),
    assignment_id        bigint      REFERENCES daily_assignments (id),
    reward_redemption_id bigint,
    created_at           timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS points_ledger_user_idx ON points_ledger (user_id);

-- Защита от двойного начисления по одной задаче (NULL-значения не конфликтуют).
CREATE UNIQUE INDEX IF NOT EXISTS points_ledger_assignment_reason_uniq
    ON points_ledger (assignment_id, reason);

-- Список наград, который пополняется взрослым.
CREATE TABLE IF NOT EXISTS rewards (
    id         bigserial PRIMARY KEY,
    title      text        NOT NULL,
    cost       integer     NOT NULL CHECK (cost > 0),
    is_active  boolean     NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS rewards_title_uniq ON rewards (lower(title));

-- Заявки на получение наград: баллы списываются сразу, выдача — вручную.
CREATE TABLE IF NOT EXISTS reward_redemptions (
    id         bigserial PRIMARY KEY,
    user_id    text        NOT NULL,
    reward_id  bigint      NOT NULL REFERENCES rewards (id),
    title      text        NOT NULL,
    cost       integer     NOT NULL,
    status     text        NOT NULL DEFAULT 'requested'
                           CHECK (status IN ('requested', 'issued', 'cancelled')),
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Текущая цель ребёнка: на какую награду он копит.
CREATE TABLE IF NOT EXISTS user_goals (
    user_id    text PRIMARY KEY,
    reward_id  bigint      NOT NULL REFERENCES rewards (id),
    created_at timestamptz NOT NULL DEFAULT now()
);
