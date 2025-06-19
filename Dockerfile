FROM python:3.11-slim

RUN apt-get update && \
    apt-get upgrade -y \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /usr/app/

RUN mkdir -p /usr/app/cache

ADD requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ADD spoopafubot.py /usr/bin/spoopafubot
RUN chmod +x /usr/bin/spoopafubot

WORKDIR /usr/app/cache

CMD [ "/usr/bin/spoopafubot" ]