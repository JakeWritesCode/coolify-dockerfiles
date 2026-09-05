# syntax=docker/dockerfile:1.7

FROM node:22-bookworm-slim AS node
FROM golang:1.27.0-bookworm

ARG GOLANGCI_LINT_VERSION=v2.13.1
ARG CODEX_VERSION=0.147.0
ARG OPENCODE_VERSION=1.18.27

ENV DEBIAN_FRONTEND=noninteractive \
    GOPATH=/opt/go \
    GOBIN=/usr/local/bin \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    PATH=/opt/go/bin:/usr/local/go/bin:/home/dev/.local/bin:${PATH}

RUN apt-get -o Acquire::Retries=3 update \
    && apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
        bash \
        build-essential \
        ca-certificates \
        curl \
        git \
        gnupg \
        jq \
        make \
        postgresql-client \
        procps \
        python3 \
        python3-pip \
        python3-venv \
        ripgrep \
        tini \
        tmux \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL --retry 3 https://download.docker.com/linux/debian/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && chmod a+r /etc/apt/keyrings/docker.gpg \
    && printf '%s\n' \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian bookworm stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
        docker-buildx-plugin \
        docker-ce-cli \
        docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

COPY --from=node /usr/local /usr/local

RUN ln -sf /usr/local/go/bin/* /usr/local/bin/

RUN npm install --global \
        "@openai/codex@${CODEX_VERSION}" \
        "opencode-ai@${OPENCODE_VERSION}"

RUN go install \
        "github.com/golangci/golangci-lint/v2/cmd/golangci-lint@${GOLANGCI_LINT_VERSION}"

# Create the runtime user before anything writes into /home/dev.
RUN groupadd --gid 1000 dev \
    && useradd \
        --uid 1000 \
        --gid dev \
        --create-home \
        --shell /bin/bash \
        dev \
    && install -d \
        --owner=dev \
        --group=dev \
        /workspace \
        /opt/go \
        /home/dev/.config \
        /home/dev/.config/opencode \
        /home/dev/.cache \
        /home/dev/.cache/opencode \
        /home/dev/.local \
        /home/dev/.local/bin \
        /home/dev/.local/share \
        /home/dev/.local/share/opencode \
        /home/dev/.local/state \
        /home/dev/.local/state/opencode \
    && chown -R dev:dev /home/dev /workspace /opt/go

ENV HOME=/home/dev

# Install Coolify CLI into dev's own ~/.local/bin.
RUN su - dev -c 'curl -fsSL \
    https://raw.githubusercontent.com/coollabsio/coolify-cli/main/scripts/install.sh \
    | bash -s -- --user'

RUN go version \
    && node --version \
    && npm --version \
    && codex --version \
    && opencode --version \
    && /home/dev/.local/bin/coolify version \
    && docker --version \
    && docker compose version \
    && docker buildx version \
    && golangci-lint --version

USER dev
WORKDIR /workspace

EXPOSE 4096

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["opencode", "serve", "--hostname", "0.0.0.0", "--port", "4096"]