# ---- builder stage ----
FROM python:3.12-alpine AS builder

RUN apk add --no-cache \
    gcc \
    musl-dev \
    libffi-dev \
    openssl-dev \
    cargo

WORKDIR /app

COPY requirements/ requirements/
COPY setup.py setup.cfg MANIFEST.in ./

RUN pip install --no-cache-dir --user \
    -r requirements/prod.txt

# ---- runtime stage ----
FROM python:3.12-alpine

RUN apk add --no-cache \
    libffi \
    openssl \
    && addgroup -S passportd \
    && adduser -S passportd -G passportd

COPY --from=builder /root/.local /home/passportd/.local

ENV PATH="/home/passportd/.local/bin:${PATH}"
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY passportd/ passportd/
COPY setup.py setup.cfg MANIFEST.in ./

RUN pip install --no-cache-dir -e . \
    && mkdir -p /app/data /app/logs /app/uploads \
    && chown -R passportd:passportd /app

USER passportd

EXPOSE 10030

ENTRYPOINT ["passportd"]
CMD ["start"]
