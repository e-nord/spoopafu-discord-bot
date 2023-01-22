FROM python:3
ADD spootifybot.py /
RUN pip install -r requirements.txt
CMD [ "python", "spootifybot.py" ]