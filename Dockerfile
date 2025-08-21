FROM python:3.13-alpine

COPY . /app
WORKDIR /app

RUN pip install -r requirements.txt
CMD ["python", "brobot.py"]