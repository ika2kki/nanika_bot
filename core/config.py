import tomllib
from typing import TypedDict


class Discord(TypedDict):
    token: str

class PostgreSQL(TypedDict):
    uri: str

class gelbooru(TypedDict):
    api_key: str
    user_id: str

class GitHub(TypedDict):
    me: str
    repository: str
    branch: str

class Lavalink(TypedDict):
    url: str
    password: str

class fernet(TypedDict):
    secret: str

class Config(TypedDict):
    discord: Discord
    postgresql: PostgreSQL
    gelbooru: gelbooru
    github: GitHub
    fernet: fernet

with open("config.toml", "rb") as f:
    configs: Config = tomllib.load(f)
