#!/usr/bin/env python3

from dataclasses import dataclass
import discord
import spotipy
import re
import os
import logging
import http.server
import threading

class WebConsoleHTTPServer:

    def __init__(self, port):
        self.port = port
        server_address = ('', self.port)
        self.server = http.server.HTTPServer(server_address, http.server.SimpleHTTPRequestHandler)
        self.thread = threading.Thread(target=self._run, args=(self.server, ))

    def start(self):
        self.thread.start()

    def _run(self, httpd):
        httpd.serve_forever()
        
class MessageScannerDiscordClient(discord.Client):

    def __init__(self, message_handlers):
        self.message_handlers = message_handlers
        self.logger = logging.getLogger(self.__class__.__name__)
        super().__init__()

    async def on_ready(self):
        self.logger.info(f'{self.user.name} has connected to Discord!')
        for guild in self.guilds:
            self.logger.info(f'Serving guild: {guild}')

    async def on_message(self, message):
        self.logger.info(f"Received message: {message.content}")
        try:
            for message_handler in self.message_handlers:
                reply = message_handler.handle_message(message.content)
                if reply:
                    await message.channel.send(reply)
        except Exception as e:
            self.logger.error(e)

    async def on_error(self, event, *args, **kwargs):
        if event == 'on_message':
            self.logger.warning(f"error: {args[0]}")
        else:
            raise

class GoodBotMessageScanner:

    def __init__(self):
        self.good_bot_regex = re.compile("g[o]{2,}d\s.*\sbot", re.IGNORECASE)

    def handle_message(self, message_content):
        reply = None

        match = self.good_bot_regex.search(message_content)
        if match:
            reply = ":flushed:"

        return reply

class SpotifyMessageScanner:
    def __init__(self, spotify, playlist_id):
        self.spotify = spotify
        self.playlist_id = playlist_id
        self.logger = logging.getLogger(self.__class__.__name__)
        self.song_metadata_regex = re.compile("\<(.*?)\>")
    
    def __add_track_to_playlist(self, track_id):
        items = [track_id]
        self.spotify.playlist_remove_all_occurrences_of_items(self.playlist_id, items)
        result = self.spotify.playlist_add_items(self.playlist_id, items)
        if not result:
            self.logger.warning("No response from add playlist items call")
        else:
            self.logger.debug(result)

    def handle_message(self, message_content):
        reply = None

        match = self.song_metadata_regex.search(message_content)
        if match:
            song_metadata = match.group(1)
            self.logger.debug(f"Found a song in a message! It's: {song_metadata}")

            song_metadata = song_metadata.replace("-", "")

            self.logger.debug(f"Searching for Spotify track...")
            results = self.spotify.search(q=f'{song_metadata}', type='track')
            if results:
                self.logger.debug(f"Found something: {results}")

                query_items = results['tracks']['items']
                if len(query_items):
                    track = results['tracks']['items'][0]
                    spotify_url = track['external_urls']['spotify']

                    self.logger.debug(f"{track}")
                    self.logger.debug(f"Spotify URL: {spotify_url}")

                    track_id = track['id']
                    self.logger.debug(f"Adding track {track_id} to playlist {self.playlist_id}")
                    self.__add_track_to_playlist(track_id)

                    reply = spotify_url
                else:
                    self.logger.warning("No query results found")
            else:
                self.logger.warning("No response from search call")

        return reply

@dataclass
class SpotifyAppConfig:
    def __init__(self, username=None, client_id=None, client_secret=None, redirect_uri=None, playlist_id=None):
        self.username = os.environ.get("SPOTIFY_USERNAME", username)
        self.client_id = os.environ.get("SPOTIFY_CLIENT_ID", client_id)
        self.client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", client_secret)
        self.redirect_uri = os.environ.get("SPOTIFY_REDIRECT_URI", f'{redirect_uri}')
        self.playlist_id = os.environ.get("SPOTIFY_PLAYLIST_ID", playlist_id)
        self.token_cache = os.environ.get("TOKEN_CACHE")
        self.token_cache_file = '.cache-{}'.format(self.username)

    def maybe_write_token_cache_file(self):
        if not os.path.exists(self.token_cache_file):
            if self.token_cache:
                with open(self.token_cache_file, 'w') as cache_file:
                    cache_file.write(self.token_cache)
            else:
                logging.warning("TOKEN_CACHE environment variable not set, unable to write OAuth token cache file")

import time
@dataclass
class DiscordAppConfig:
    def __init__(self, token=None):
        self.token = os.environ.get("DISCORD_TOKEN", token)

class SpootifyBot:

    SCOPE = "playlist-modify-public playlist-read-collaborative playlist-modify-private"

    def __init__(self, spotify_config, discord_config):
        self.discord_client_token = discord_config.token
        auth_manager = spotipy.SpotifyOAuth(
            username=spotify_config.username,
            client_id=spotify_config.client_id,
            client_secret=spotify_config.client_secret,
            redirect_uri=spotify_config.redirect_uri,
            scope=SpootifyBot.SCOPE,
            open_browser=False)
        self.spotify = spotipy.Spotify(auth_manager=auth_manager)
        self.spotify_message_scanner = SpotifyMessageScanner(self.spotify, playlist_id=spotify_config.playlist_id)
        self.good_boy_message_scanner = GoodBotMessageScanner()
        scanners = [self.spotify_message_scanner, self.good_boy_message_scanner]
        self.discord_client = MessageScannerDiscordClient(scanners)

    def run(self):
        #Authenticate by firing off a test request
        logging.info("Firing off Spotify API call...")
        results = self.spotify.current_user()
        logging.debug(results)

        self.discord_client.run(self.discord_client_token)

def main():
    log_level = os.environ.get('LOGLEVEL', 'DEBUG').upper()
    logging.basicConfig(level=log_level)

    port = int(os.environ.get('PORT', 8080))
    
    logging.info(f"Listening on port {port}")
    console = WebConsoleHTTPServer(port)
    console.start()

    spotify_config = SpotifyAppConfig()
    spotify_config.maybe_write_token_cache_file()

    discord_config = DiscordAppConfig()

    logging.info("Starting bot...")
    bot = SpootifyBot(spotify_config=spotify_config, discord_config=discord_config)
    bot.run()

if __name__ == '__main__':
    main()