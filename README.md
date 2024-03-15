## nanika_bot

inspired by lots of other bot

## contributing

anything welcome- thanks you a lot

<a href="https://github.com/ika2kki/nanika_bot/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=ika2kki/nanika_bot" />
</a>

### self-hosting for test

stuff to install:
- postgresql for the database
- poetry for venv/dependencies
- tesseract ocr
- java 17 or any LTS version above

some stuff is optional depending how u want to run bot and what cog you have but this is how i do it

type this statements in `psql` tool to create the database for the bot:

```shell
$ sudo -u postgres pgsql
```

```pgsql
CREATE USER nanika_bot WITH ENCRYPTED PASSWORD 'nanika';
CREATE DATABASE nanika_bot WITH OWNER nanika_bot;
GRANT ALL PRIVILEGES ON DATABASE nanika_bot TO nanika_bot;
\connect nanika_bot
CREATE EXTENSION pg_trgm;
```

install tesseract - on debian you can do this with:
- `apt install tesseract-ocr` for the program itself
- `apt install tesseract-ocr-jpn` and `tesseract-ocr-eng` for the trained language data

download lavalink - you can do this by downloading the appriopate release from the lavalink repo (v4.0+)

```shell
$ wget https://github.com/lavalink-devs/Lavalink/releases/download/4.0.0-beta.5/Lavalink.jar
```

to make the venv with poetry, do this from within same folder as `pyproject.toml`:

```shell
$ poetry install
```

add configuration in `config.toml`~ spec is outlined in [`config.toml`](core/config.py).:

now this pair of commands needs to be used to run the bot:
```shell
$ java -jar Lavalink.jar
$ poetry run python -O app.py
```

personally, i run bot by spawning two screen sessions, but you can use whatever