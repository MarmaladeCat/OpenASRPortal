FROM python:3.12.10-slim-bookworm
WORKDIR /app
COPY requirements.txt ./
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
COPY LICENSE ./LICENSE
COPY packaging/docker/entrypoint.py ./entrypoint.py
RUN useradd --uid 10001 --create-home portal && mkdir /data && chown portal:portal /data
ENV OPENASRPORTAL_HOST=127.0.0.1 OPENASRPORTAL_DATA=/data PYTHONPATH=/app/src PYTHONDONTWRITEBYTECODE=1
USER portal
EXPOSE 10087
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:10087/health', timeout=2)"
CMD ["python", "/app/entrypoint.py"]
