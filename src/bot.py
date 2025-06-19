import discord
from discord.ext import commands
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import os
import re
import asyncio
from typing import Optional, Dict, Any
from langchain_ollama import OllamaLLM
from langchain_ollama import OllamaEmbeddings
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SpotifyAgent:
    """Handles Spotify data retrieval"""

    def __init__(self, spotify_client_id: str, spotify_client_secret: str):
        # Initialize Spotify client
        client_credentials_manager = SpotifyClientCredentials(
            client_id=spotify_client_id, client_secret=spotify_client_secret
        )
        self.spotify = spotipy.Spotify(
            client_credentials_manager=client_credentials_manager
        )

        # Song pattern for parsing messages
        self.song_pattern = re.compile(
            r'(?:song|track|music).*?["\']([^"\']+)["\'].*?(?:by|artist|from)\s*["\']?([^"\']+)["\']?|'
            r'["\']([^"\']+)["\'].*?(?:by|artist|from)\s*["\']([^"\']+)["\']|'
            r"(?:play|find|search)\s+(.+?)\s+(?:by|from)\s+(.+?)(?:\s|$)",
            re.IGNORECASE,
        )

    async def search_spotify_track(
        self, song_name: str, artist_name: str
    ) -> Optional[Dict[str, Any]]:
        """Search for a track on Spotify and return track info"""
        try:
            # Clean and format search query
            if artist_name:
                query = f"track:{song_name} artist:{artist_name}"
            else:
                query = f"track:{song_name}"
            results = self.spotify.search(q=query, type="track", limit=1)

            if results["tracks"]["items"]:
                track = results["tracks"]["items"][0]
                return {
                    "name": track["name"],
                    "artist": ", ".join(
                        [artist["name"] for artist in track["artists"]]
                    ),
                    "url": track["external_urls"]["spotify"],
                    "release_date": track["album"]["release_date"],
                    "album": track["album"]["name"],
                    "popularity": track["popularity"],
                    "duration_ms": track["duration_ms"],
                    "thumbnail_url": track["album"]["images"][0]["url"],
                }
            return None
        except Exception as e:
            logger.error(f"Spotify search error: {e}")
            return None

    def extract_song_info(self, message: str) -> Optional[tuple]:
        """Extract song name and artist from message using regex"""
        matches = self.song_pattern.findall(message)

        for match in matches:
            # Handle different regex group patterns
            if match[0] and match[1]:  # "song" by "artist"
                return (match[0].strip(), match[1].strip())
            elif match[2] and match[3]:  # "song" by artist
                return (match[2].strip(), match[3].strip())
            elif match[4] and match[5]:  # play song by artist
                return (match[4].strip(), match[5].strip())

        # Fallback: try to parse common patterns
        simple_patterns = [
            r"(.+?)\s+by\s+(.+?)(?:\s|$)",
            r"(.+?)\s*-\s*(.+?)(?:\s|$)",
        ]

        for pattern in simple_patterns:
            match = re.search(pattern, message, re.IGNORECASE)
            if match:
                return (match.group(1).strip(), match.group(2).strip())

        return (f'"{message}"', None)


class General(commands.Cog):
    @commands.command()
    async def greet(self, ctx, name: str):
        await ctx.send(f"Whaddup {name}!")


class LLM(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot: MusicBot = bot  # Store a reference to the bot if needed

        # Store user conversation history and preferences
        self.user_preferences = {}  # user_id -> list of preferences/songs
        self.conversation_history = {}  # user_id -> list of recent messages

        self.llm = OllamaLLM(model="artifish/llama3.2-uncensored")

    @commands.command()
    async def chat(self, ctx, message: str):
        """Direct chat with the bot"""

        # Create a mock message object for handle_llm_conversation
        mock_message = type(
            "MockMessage",
            (),
            {
                "content": message,
                "channel": ctx.channel,
                "author": ctx.author,
                "reply": ctx.send,
            },
        )()

        await self.handle_llm_conversation(mock_message)

    async def handle_llm_conversation(self, message):
        """Handle general conversation using Ollama LLM"""
        try:
            # Show typing indicator
            async with message.channel.typing():
                user_id = str(message.author.id)

                # Update conversation history
                if user_id not in self.conversation_history:
                    self.conversation_history[user_id] = []

                self.conversation_history[user_id].append(message.content)
                # Keep only last 10 messages
                self.conversation_history[user_id] = self.conversation_history[user_id][
                    -10:
                ]

                # Clean the message content (remove mentions, bot name, etc.)
                content = message.content
                content = content.replace(f"<@{self.bot.user.id}>", "").replace(
                    f"<@!{self.bot.user.id}>", ""
                )
                content = content.replace(f"{self.bot.user.name}", "").replace(
                    "bot", ""
                )
                content = content.strip()

                if not content:
                    content = "Wut do?"

                # Get user's music preferences for context
                user_prefs = self.user_preferences.get(user_id, [])
                prefs_context = (
                    f"User's music preferences: {', '.join(user_prefs[-5:])}"
                    if user_prefs
                    else ""
                )

                # Create a music-focused prompt with user context
                music_prompt = f"""
                    You are a helpful music assistant bot in a Discord server. You can:
                    1. Help users find songs on Spotify
                    2. Recommend music based on preferences
                    3. Answer questions about music, artists, and genres
                    4. Have casual conversations about music
                    
                    {prefs_context}
                    
                    Keep responses concise (under 1500 characters) and friendly.
                    If asked about finding specific songs, mention they can ask like: "Find 'song name' by 'artist name'"
                    
                    User message: {content}
                    
                    Response:"""

                # Use LLM for general conversation
                llm_response = await asyncio.get_event_loop().run_in_executor(
                    None, self.llm.invoke, music_prompt
                )

                # Clean and send response
                response = llm_response.strip()
                if response:
                    # Split long responses if needed
                    if len(response) > 2000:
                        # Split at sentence boundaries
                        sentences = response.split(". ")
                        current_chunk = ""

                        for sentence in sentences:
                            if len(current_chunk + sentence + ". ") <= 2000:
                                current_chunk += sentence + ". "
                            else:
                                if current_chunk:
                                    await message.reply(current_chunk.strip())
                                current_chunk = sentence + ". "

                        if current_chunk:
                            await message.reply(current_chunk.strip())
                    else:
                        await message.reply(response)
                else:
                    await message.reply(
                        "I'm having trouble processing that right now. Try asking about music!"
                    )

        except Exception as e:
            logger.error(f"Error in LLM conversation: {e}")
            await message.reply(
                "Sorry, I'm having trouble responding right now. Try asking me things with !chat or search songs with the !find command!"
            )


class Spotify(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot: MusicBot = bot  # Store a reference to the bot if needed

    @commands.command()
    async def song(self, ctx, *, message: str):
        # Create a mock message object for handle_llm_conversation
        mock_message = type(
            "MockMessage",
            (),
            {
                "content": message,
                "channel": ctx.channel,
                "author": ctx.author,
                "reply": ctx.send,
            },
        )()

        print(f"Extracting from: {mock_message.content}")
        
        # Check for song requests in natural language
        song_info = self.bot.spotify_agent.extract_song_info(mock_message.content)

        if song_info:
            song_name, artist_name = song_info
            print(f"Extracted: {song_info}")
            await self.handle_song_request(mock_message, song_name, artist_name)

    async def handle_song_request(self, message, song_name: str, artist_name: str):
        """Handle song requests found in messages"""
        try:
            # Search for the track
            track_info = await self.bot.spotify_agent.search_spotify_track(
                song_name, artist_name
            )

            if track_info:
                embed = discord.Embed(
                    title="🎵  Found your song!",
                    description=f"**{track_info['name']}** by **{track_info['artist']}**",
                    color=0x1DB954,  # Spotify green
                )
                embed.set_image(url=track_info["thumbnail_url"])
                embed.add_field(name="Album", value=track_info["album"], inline=True)
                embed.add_field(
                    name="Popularity",
                    value=f"{track_info['popularity']}/100",
                    inline=True,
                )
                embed.add_field(
                    name="Duration",
                    value=f"{track_info['duration_ms']//1000//60}:{(track_info['duration_ms']//1000)%60:02d}",
                    inline=True,
                )
                embed.add_field(
                    name="Spotify Link",
                    value=f"[Listen on Spotify]({track_info['url']})",
                    inline=False,
                )

                await message.channel.send(embed=embed)
            else:
                await message.channel.send(
                    f"Sorry, I couldn't find '{song_name}' by '{artist_name}' on Spotify. 😔"
                )

        except Exception as e:
            logger.error(f"Error handling song request: {e}")
            await message.channel.send(
                "Sorry, there was an error processing your song request."
            )


class MusicBot(commands.Bot):
    """Discord bot that handles music queries and Spotify integration"""

    def __init__(self, spotify_agent: SpotifyAgent):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents)

        self.spotify_agent = spotify_agent

    async def on_ready(self):
        print(f"{self.user} has connected to Discord!")

        for guild in self.guilds:
            logger.info("Serving guild: %s", guild)

    async def setup_hook(self):
        await self.add_cog(General())
        await self.add_cog(LLM(self))
        await self.add_cog(Spotify(self))

    async def on_message(self, message):
        # Ignore bot messages
        if message.author == self.user or message.author.bot:
            return

        # Process commands first
        await self.process_commands(message)


def main():
    """Main function to run the bot"""

    # Load environment variables
    DISCORD_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
    SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

    if not all([DISCORD_TOKEN, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET]):
        print("Please set the required environment variables:")
        print("- DISCORD_BOT_TOKEN")
        print("- SPOTIFY_CLIENT_ID")
        print("- SPOTIFY_CLIENT_SECRET")
        return

    spotify_agent = SpotifyAgent(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET)

    # Initialize and run bot
    bot = MusicBot(spotify_agent)

    try:
        bot.run(DISCORD_TOKEN)
    except Exception as e:
        logger.error(f"Error running bot: {e}")


if __name__ == "__main__":
    main()
