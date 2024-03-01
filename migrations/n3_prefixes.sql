CREATE TABLE bot_prefixes (
    id BIGINT PRIMARY KEY,
    prefixes TEXT[] NOT NULL
);

/*
prefixes are stored in array instead of by row
because [] is valid (only mention) and i dont have a way
to easily do that for a row-based approach (no rows = defaults or mentions?)
i can have another table to store whether prefixes are considered "touched" or "dirty"
eg. prefix_states(id INT, touched BOOL) so i know how to tell but i dont think this is worth it
*/
