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
        netcat-openbsd \
        openssh-client \
        openssh-server \
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

# Agent CLIs — pinned so rebuilds are reproducible.
RUN npm install --global \
        "@openai/codex@${CODEX_VERSION}" \
        "opencode-ai@${OPENCODE_VERSION}"

RUN go install \
        "github.com/golangci/golangci-lint/v2/cmd/golangci-lint@${GOLANGCI_LINT_VERSION}"

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
        /home/dev/.codex \
        /home/dev/.config \
        /home/dev/.cache \
        /home/dev/.local/share \
        /home/dev/.local/state \
        /home/dev/.ssh \
    && install -d -m 0755 /run/sshd \
    && chown -R dev:dev \
        /home/dev/.codex \
        /home/dev/.config \
        /home/dev/.cache \
        /home/dev/.local

RUN printf '%s\n' \
        'Port 22' \
        'AddressFamily any' \
        'ListenAddress 0.0.0.0' \
        'ListenAddress ::' \
        'PermitRootLogin no' \
        'PasswordAuthentication no' \
        'KbdInteractiveAuthentication no' \
        'ChallengeResponseAuthentication no' \
        'PubkeyAuthentication yes' \
        'AuthorizedKeysFile .ssh/authorized_keys' \
        'AllowUsers dev' \
        'AllowAgentForwarding no' \
        'AllowTcpForwarding no' \
        'GatewayPorts no' \
        'X11Forwarding no' \
        'PermitTunnel no' \
        'PermitUserEnvironment no' \
        'PrintMotd no' \
        'UsePAM no' \
        'Subsystem sftp internal-sftp' \
        > /etc/ssh/sshd_config

COPY --chmod=0755 docker-entrypoint.sh /usr/local/bin/dev-entrypoint

RUN go version \
    && node --version \
    && npm --version \
    && npx --version \
    && corepack --version \
    && codex --version \
    && opencode --version \
    && docker --version \
    && docker compose version \
    && docker buildx version \
    && golangci-lint --version \
    && sshd -t

ENV HOME=/home/dev

WORKDIR /workspace

EXPOSE 22 4096

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/dev-entrypoint"]
CMD ["/usr/sbin/sshd", "-D", "-e"]