## BROBOT

Discord bot.

## Local Development

Build

```sh
docker build . --tag brobot:latest
```

Run

```sh 
docker run brobot:latest --name=brobot -e DISCORD_KEY=${DISCORD_KEY}
```