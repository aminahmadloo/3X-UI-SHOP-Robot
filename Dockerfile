FROM python:3.12-slim-bookworm

ENV PYTHONPATH=/
ENV POETRY_VIRTUALENVS_CREATE=false

COPY pyproject.toml poetry.lock /

RUN apt-get update \
    && apt-get install -y --no-install-recommends iputils-ping traceroute \
    && rm -rf /var/lib/apt/lists/* \
    && pip install poetry \
    && poetry install

COPY ./app /app
