FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg

RUN addgroup --system sandbox && adduser --system --ingroup sandbox sandbox

RUN pip install --no-cache-dir \
    numpy==2.1.3 \
    pandas==2.2.3 \
    scipy==1.14.1 \
    matplotlib==3.9.2 \
    openpyxl==3.1.5

WORKDIR /opt/sandbox
COPY src/sandbox_service/runtime/runtime_wrapper.py /opt/sandbox/runtime_wrapper.py

USER sandbox
