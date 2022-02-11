FROM python:3
RUN pip install spotipy discord.py
ADD spootifybot.py /
CMD [ "python", "spootifybot.py" ]