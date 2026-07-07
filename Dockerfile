FROM docker.repo.severstal.severstalgroup.com/devops-public/corp-images/python:3.12-debian
USER root

ENV PATH=/home/user/.local/bin:$PATH
ENV TZ=Europe/Moscow

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SANDBOX_RUNNER=subprocess

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY src /app/src

RUN pip3 config --global set global.trusted-host repo.severstal.severstalgroup.com; \
    pip3 config --global set global.index-url https://repo.severstal.severstalgroup.com/artifactory/api/pypi/pypi/simple

RUN pip3 install --no-cache-dir .

RUN addgroup --system app && adduser --system --ingroup app app

COPY . .

USER app

EXPOSE 8080
CMD ["uvicorn", "sandbox_service.main:app", "--host", "0.0.0.0", "--port", "8080"]
