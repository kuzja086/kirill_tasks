-- Начальная схема навыка.
-- Применение: psql -h <хост> -U alice_skill -d alice_skill -f sql/001_init.sql

CREATE TABLE IF NOT EXISTS skill_users (
    user_id      text PRIMARY KEY,
    display_name text        NOT NULL,
    created_at   timestamptz  NOT NULL DEFAULT now(),
    updated_at   timestamptz  NOT NULL DEFAULT now()
);

COMMENT ON TABLE skill_users IS 'Пользователи навыка Алисы';
COMMENT ON COLUMN skill_users.user_id IS
    'Анонимный идентификатор из session.user.user_id; уникален в пределах навыка';
COMMENT ON COLUMN skill_users.display_name IS 'Имя, которое пользователь назвал навыку';
