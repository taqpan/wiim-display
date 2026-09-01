# 開発用イメージ。Pi 実機（Raspberry Pi OS 13 / trixie / Python 3.13）と
# OS 系列と Python バージョンを揃える。CPU アーキテクチャは揃えない。
FROM python:3.13-slim-trixie

# ワークツリーを /app に bind mount するため、venv はその外に置く
ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Pillow の実行時依存（docs/setup-pi.md §6 と同じ）
RUN apt-get update \
 && apt-get install -y --no-install-recommends libopenjp2-7 \
 && rm -rf /var/lib/apt/lists/*

# bind mount 上に root 所有のファイルを作らないよう、ホストと同じ uid/gid で実行する
ARG UID=1000
ARG GID=1000
RUN groupadd -g "${GID}" app \
 && useradd -m -u "${UID}" -g "${GID}" app \
 && python3 -m venv "${VIRTUAL_ENV}" \
 && chown -R "${UID}:${GID}" "${VIRTUAL_ENV}"

WORKDIR /app
USER app

COPY --chown=app:app pyproject.toml README.md ./
COPY --chown=app:app src ./src
RUN pip install --no-cache-dir -e '.[dev]'

EXPOSE 8080
CMD ["python", "-m", "wiim_display.server"]
