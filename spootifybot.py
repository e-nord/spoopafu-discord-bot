#!/usr/bin/env python3

import asyncio
from dataclasses import dataclass
import datetime
import discord
import spotipy
import re
import os
import logging
import http.server
import threading
import requests
import time

class StoppableThread(threading.Thread):

    def __init__(self):
        super(StoppableThread, self).__init__()
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def join(self, *args, **kwargs):
        self.stop()
        super(StoppableThread,self).join(*args, **kwargs)

    def is_stopped(self):
        return self._stop_event.is_set()

class PingThread(StoppableThread):
    def __init__(self, ping_url, ping_interval_sec):
        super(PingThread, self).__init__()
        self.ping_url = ping_url
        self.daemon = True
        self.ping_interval_sec = ping_interval_sec
        self.logger = logging.getLogger(self.__class__.__name__)

    def start(self) -> None:
        self.logger.info("Starting ping keepalive...")
        return super().start()

    def run(self):
        while not self.is_stopped():
            resp = requests.get(self.ping_url)
            self.logger.info(resp)
            time.sleep(self.ping_interval_sec)
    

class WebConsoleHTTPServer:

    def __init__(self, port):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.port = port
        server_address = ('', self.port)
        self.logger.info(f"Listening on port {port}")
        self.server = http.server.HTTPServer(server_address, http.server.SimpleHTTPRequestHandler)
        self.thread = threading.Thread(target=self._run, args=(self.server, ))
        self.thread.daemon = True

    def start(self):
        self.thread.start()

    def _run(self, httpd: http.server.HTTPServer):
        httpd.serve_forever()
        
        
class MessageScanner:
    def is_match(message: discord.Message):
        pass
    
    def handle_message(discord_client: discord.Client, message: discord.Message):
        pass
        
class MessageScannerDiscordClient(discord.Client):

    def __init__(self, message_handlers: list[MessageScanner]):
        self.message_handlers = message_handlers
        self.logger = logging.getLogger(self.__class__.__name__)
        self.ready_timestamp = None
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)

    async def search_old_messages(self, channel: discord.TextChannel, message_handler: MessageScanner):
        self.logger.info(f"Looking back over messages from before being ready: {self.ready_timestamp}")

        async with channel.typing():

            old_messages: list[discord.Message] = [message async for message in channel.history(limit=100, before=self.ready_timestamp) ]
            
            old_message_to_handle = []
            for old_message in old_messages:
                self.logger.info(f"Checking msg: {old_message.content} sent at {old_message.created_at} by {old_message.author}")
                
                last_message = old_message
                
                if old_message.author == self.user:
                    self.logger.info(f"All caught up with messages. Recent bot reply at {old_message.created_at.isoformat()}")
                    break
                
                if message_handler.is_match(old_message):
                    old_message_to_handle.append(old_message)
                    
            await asyncio.sleep(3)

            if len(old_message_to_handle) > 0:
                
                await channel.send("These were here all along I swear :sunglasses:")
                await asyncio.sleep(2)
                
                for old_message in old_message_to_handle:
                    reply = message_handler.handle_message(self, old_message)
                    await channel.send(reply, reference=old_message)
                    
            else:
                await asyncio.sleep(5)
                await channel.send("Phew nothing happened while I was gone :relieved:")
                
            self.ready_timestamp = last_message.created_at

    async def on_ready(self):
        self.logger.info(f'{self.user.name} has connected to Discord!')
        for guild in self.guilds:
            self.logger.info(f'Serving guild: {guild}')
        self.ready_timestamp = datetime.datetime.now()
            
    async def on_message(self, message: discord.Message):
        self.logger.info(f"Received message: {message.content}")
        try:
            for message_handler in self.message_handlers:
                reply = message_handler.handle_message(self, message)
                if reply:
                    await message.channel.send(reply, reference=message)
        except Exception as e:
            self.logger.error(f"on_message: {e}")
            await message.channel.send("Whoops that hurt my brain...maybe try again?")


    async def on_error(self, event, *args, **kwargs):
        if event == 'on_message':
            self.logger.warning(f"error: {args[0]}")
        else:
            raise

class BotEmoteReactionMessageScanner:

    REACTIONS = [
        ("b[a]{1,}d\s+b[o0]t", ":sob:"),
        ("g[o0]{2,}d\s+b[o0]t", ":flushed:")
    ]
    
    def __init__(self):
        self.patterns = [(re.compile(pair[0], re.IGNORECASE), pair[1]) for pair in BotEmoteReactionMessageScanner.REACTIONS]

    def is_match(self, message: discord.Message):
        for regex,_ in self.patterns:
            match = regex.search(message.content)
            if match:
                return True
        return False

    def handle_message(self, discord_client: MessageScannerDiscordClient, message: discord.Message):
        for regex,emote in self.patterns:
            match = regex.search(message.content)
            if match:
                return emote

        return None

class SpotifyMessageScanner:
    def __init__(self, spotify: spotipy.Spotify, playlist_id: str):
        self.spotify = spotify
        self.playlist_id = playlist_id
        self.logger = logging.getLogger(self.__class__.__name__)
        self.song_metadata_regex = re.compile("\<(.*?)\>")
    
    def __add_track_to_playlist(self, track_id: str):
        items = [track_id]
        self.spotify.playlist_remove_all_occurrences_of_items(self.playlist_id, items)
        result = self.spotify.playlist_add_items(self.playlist_id, items)
        if not result:
            self.logger.warning("No response from add playlist items call")
        else:
            self.logger.debug(result)
            
    def is_match(self, message: discord.Message):
        return self.song_metadata_regex.search(message.content) is not None

    def handle_message(self, discord_client: MessageScannerDiscordClient, message: discord.Message):
        reply = None

        match = self.song_metadata_regex.search(message.content)
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

class WakeUpMessageScanner:

    REGEX = "w[a+]ke[\s+]?[u+]p[\s+]b[o+]t[!+]?"

    BOT_REPLIES = [
        "Oh my :flushed: I must have dozed off...let me see what I've missed"
    ]
    
    def __init__(self, spotify_message_scanner: SpotifyMessageScanner):
        self.regex = re.compile(WakeUpMessageScanner.REGEX, re.IGNORECASE)
        self.spotify_message_scanner = spotify_message_scanner

    def is_match(self, message: discord.Message):
        return self.regex.search(message.content) is not None

    def handle_message(self, discord_client: MessageScannerDiscordClient, message: discord.Message):
        match = self.regex.search(message.content)
        if match:
            discord_client.loop.create_task(discord_client.search_old_messages(message.channel, self.spotify_message_scanner))
            return WakeUpMessageScanner.BOT_REPLIES[0]

        return None
@dataclass
class SpotifyAppConfig:
    def __init__(self, username=None, client_id=None, client_secret=None, redirect_uri=None, playlist_id=None):
        self.username = os.environ.get("SPOTIFY_USERNAME", username)
        self.client_id = os.environ.get("SPOTIFY_CLIENT_ID", client_id)
        self.client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", client_secret)
        self.redirect_uri = os.environ.get("SPOTIFY_REDIRECT_URI", redirect_uri)
        self.playlist_id = os.environ.get("SPOTIFY_PLAYLIST_ID", playlist_id)
        self.token_cache = os.environ.get("TOKEN_CACHE")

    def validate(self):
        if not self.username:
            raise ValueError("Missing environment variable: SPOTIFY_USERNAME") 
        if not self.client_id:
            raise ValueError("Missing environment variable: SPOTIFY_CLIENT_ID") 
        if not self.client_secret:
            raise ValueError("Missing environment variable: SPOTIFY_CLIENT_SECRET") 
        if not self.redirect_uri:
            raise ValueError("Missing environment variable: SPOTIFY_REDIRECT_URI") 
        if not self.playlist_id:
            raise ValueError("Missing environment variable: SPOTIFY_PLAYLIST_ID") 
        
    def maybe_write_token_cache_file(self):
        token_cache_file = '.cache-{}'.format(self.username)
        if not os.path.exists(token_cache_file):
            if self.token_cache:
                with open(token_cache_file, 'w') as cache_file:
                    cache_file.write(self.token_cache)
            else:
                logging.warning("TOKEN_CACHE environment variable not set, unable to write OAuth token cache file")

@dataclass
class DiscordAppConfig:
    def __init__(self, token=None):
        self.token = os.environ.get("DISCORD_TOKEN", token)
        
    def validate(self):
        if not self.token:
            raise ValueError("Missing environment variable: DISCORD_TOKEN") 

class SpootifyBot:

    SCOPE = "playlist-modify-public playlist-read-collaborative playlist-modify-private"

    def __init__(self, spotify_config, discord_config):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.discord_client_token = discord_config.token
        auth_manager = spotipy.SpotifyOAuth(
            username=spotify_config.username,
            client_id=spotify_config.client_id,
            client_secret=spotify_config.client_secret,
            redirect_uri=spotify_config.redirect_uri,
            scope=SpootifyBot.SCOPE,
            open_browser=False)
        self.spotify = spotipy.Spotify(auth_manager=auth_manager)
        spotify_message_scanner = SpotifyMessageScanner(self.spotify, playlist_id=spotify_config.playlist_id)
        scanners = [
            spotify_message_scanner, 
            BotEmoteReactionMessageScanner(),
            WakeUpMessageScanner(spotify_message_scanner)
            ]
        self.discord_client = MessageScannerDiscordClient(scanners)

    def run(self):
        #Authenticate by firing off a test request
        self.logger.info("Firing off Spotify API call...")
        results = self.spotify.current_user()
        self.logger.debug(results)

        self.logger.info("Starting bot...")
        self.discord_client.run(self.discord_client_token)

def main():
    log_level = os.environ.get('LOGLEVEL', 'DEBUG').upper()
    logging.basicConfig(level=log_level)
    
    port = int(os.environ.get('PORT', 8080))
    
    console = WebConsoleHTTPServer(port)
    console.start()

    ping_url = os.environ.get('PING_URL')
    if ping_url:
        ping_interval_sec = int(os.environ.get('PING_INTERVAL_SEC', 60))
        keep_alive = PingThread(ping_url, ping_interval_sec)
        keep_alive.start()

    spotify_config = SpotifyAppConfig()
    spotify_config.validate()
    spotify_config.maybe_write_token_cache_file()

    discord_config = DiscordAppConfig()
    discord_config.validate()

    bot = SpootifyBot(spotify_config=spotify_config, discord_config=discord_config)
    bot.run()

if __name__ == '__main__':
    main()