FROM python:3.11-slim

RUN apt-get update && \
    apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /usr/app/

RUN mkdir -p /usr/app/cache

ADD requirements.txt .
RUN pip install -r ./requirements.txt

ADD spoopafubot.py /usr/bin/spoopafubot
RUN chmod +x /usr/bin/spoopafubot

WORKDIR /usr/app/cache

CMD [ "/usr/bin/spoopafubot" ]