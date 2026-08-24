FROM python:3.12-slim-bullseye

ENV PYTHONPATH=/
ENV POETRY_VIRTUALENVS_CREATE=false

COPY pyproject.toml poetry.lock /

RUN pip install poetry && poetry install

COPY ./app /app
