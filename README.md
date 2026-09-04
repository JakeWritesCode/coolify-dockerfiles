# Coolify Dockerfiles

I love Coolify, but I often find Dockerfiles / Docker Compose entries need a bit of fettling before they actually work. 
You can do this directly in the UI, but then while your services are cattle your server itself becomes a pet.

To combat this, this repo contains the 'state' of all my little Docker things.

## General Ideas:
- All volumes are mounted to the root FS, so I can back them up somewhere and bring the applications back up in
a DR scenario.

## Hermes extensions

- [`hermes/plugins/usage-meter`](hermes/plugins/usage-meter/README.md) attributes Hermes model usage to explicit Forgejo issue work units and persists finalized merge analytics outside application repositories.
