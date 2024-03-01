CREATE TABLE invocations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    message_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    guild_id BIGINT,
    author_id BIGINT NOT NULL,
    command TEXT,
    prefix TEXT NOT NULL
);

CREATE TABLE blame (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    message_id BIGINT NOT NULL,
    channel_id BIGINT NOT NULL,
    guild_id BIGINT,
    invocation_id BIGINT REFERENCES invocations(id)
);

CREATE INDEX blame_message_id_idx ON blame (message_id);
