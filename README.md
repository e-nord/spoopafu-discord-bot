# spoopafu discord bot

Discord bot to quick-link Spotify songs when mentioned and/or add them to a collaborative playlist

## Configuration

Copy the `env.template` to `.env` and configure the following environment variables:

``` bash
SPOTIFY_USERNAME=<spotify-username>
SPOTIFY_PLAYLIST_ID=<spotify-playlist-id>
SPOTIFY_REDIRECT_URI=<spotify-redirect-uri>
SPOTIFY_CLIENT_ID=<spotify-client-id>
SPOTIFY_CLIENT_SECRET=<spotify-client-secret>
DISCORD_TOKEN=<discord-api-token>
```

Note: The `SPOTIFY_REDIRECT_URI` will generally be `http://127.0.0.1` for headless server-side application usage

## Running

```bash
# Build container
docker compose build

# Perform one-time OAUTH authentication flow involving URL generation and browser
docker compose run --rm -ti bot spoopafubot --auth

# Up the services
docker compose up -d
```
