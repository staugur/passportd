ARG APK_MIRROR=""
ARG PIP_INDEX_URL=""

# ---- builder stage ----
FROM python:3.12-alpine AS builder

ARG APK_MIRROR
ARG PIP_INDEX_URL

RUN if [ -n "$APK_MIRROR" ]; then \
    sed -i "s@https\?://dl-cdn.alpinelinux.org/alpine@${APK_MIRROR}@g" /etc/apk/repositories; \
    fi \
    && apk add --no-cache gcc musl-dev libffi-dev openssl-dev cargo

WORKDIR /app

COPY requirements/ requirements/
COPY setup.py setup.cfg MANIFEST.in ./

RUN pip install --no-cache-dir --user ${PIP_INDEX_URL:+-i $PIP_INDEX_URL} \
    -r requirements/prod.txt

# ---- runtime stage ----
FROM python:3.12-alpine

ARG APK_MIRROR
ARG PIP_INDEX_URL

RUN if [ -n "$APK_MIRROR" ]; then \
    sed -i "s@https\?://dl-cdn.alpinelinux.org/alpine@${APK_MIRROR}@g" /etc/apk/repositories; \
    fi \
    && apk add --no-cache libffi openssl \
    && addgroup -S passportd \
    && adduser -S passportd -G passportd

COPY --from=builder /root/.local /home/passportd/.local

ENV PATH="/home/passportd/.local/bin:${PATH}"
ENV PYTHONUNBUFFERED=1
ENV PASSPORT_NO_DAEMON=true

WORKDIR /app

COPY passportd/ passportd/
COPY setup.py setup.cfg MANIFEST.in README.md ./
COPY requirements/ requirements/

RUN pip install --no-cache-dir ${PIP_INDEX_URL:+-i $PIP_INDEX_URL} -e . \
    && mkdir -p /app/data /app/logs /app/uploads \
    && chown -R passportd:passportd /app

USER passportd

EXPOSE 10030

ENTRYPOINT ["passportd"]
CMD ["start"]
