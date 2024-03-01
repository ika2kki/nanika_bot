CREATE TABLE button_views (
    id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    name TEXT NOT NULL,
    guild_id BIGINT NOT NULL,
    UNIQUE (name, guild_id),

    flags SMALLINT NOT NULL DEFAULT 0
);

CREATE TABLE button_roles (
    view_id INT REFERENCES button_views(id) ON DELETE CASCADE,
    role_id BIGINT NOT NULL,
    UNIQUE (view_id, role_id)
);