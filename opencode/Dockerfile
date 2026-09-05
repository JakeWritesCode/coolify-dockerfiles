services:
  dev:
    build:
      context: .
      dockerfile: Dockerfile

    container_name: dev

    command:
      - opencode
      - serve
      - --hostname
      - 0.0.0.0
      - --port
      - "4096"

    ports:
      - "4096:4096"

    volumes:
      - /service-data/dev/workspace:/workspace

      - /service-data/dev/opencode/share:/home/dev/.local/share/opencode
      - /service-data/dev/opencode/state:/home/dev/.local/state/opencode
      - /service-data/dev/opencode/config:/home/dev/.config/opencode
      - /service-data/dev/opencode/cache:/home/dev/.cache/opencode

      # if this thing is intentionally allowed to operate Docker:
      - /var/run/docker.sock:/var/run/docker.sock

    environment:
      TZ: ${TZ}

      OPENCODE_SERVER_USERNAME: ${OPENCODE_SERVER_USERNAME}
      OPENCODE_SERVER_PASSWORD: ${OPENCODE_SERVER_PASSWORD}

      FORGEJO_AGENT_TOKEN: ${FORGEJO_AGENT_TOKEN}
      FORGEJO_SERVER: ${FORGEJO_SERVER}

      COOLIFY_API_URL: ${COOLIFY_API_URL}
      COOLIFY_CONTEXT: ${COOLIFY_CONTEXT}
      COOLIFY_API_KEY: ${COOLIFY_API_KEY}

    restart: unless-stopped