FROM --platform=linux/amd64 python:3.11-slim

# Unbuffered stdout/stderr so worker print() output reaches CloudWatch in real
# time instead of being held in Python's buffer until the process exits.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m nltk.downloader -d /usr/local/nltk_data punkt punkt_tab

COPY . .

CMD ["python", "worker.py"]
