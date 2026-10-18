# How to Set Up a Local Development Environment

This guide walks you through setting up the service on macOS or Linux. It takes
about 15 minutes.

## Prerequisites

- Python 3.12 or newer
- Docker Desktop (or Docker Engine on Linux)
- Access to the team's GitHub organization

## Steps

1. **Clone the repository.**

   ```bash
   git clone https://github.com/example/service.git
   cd service
   ```

2. **Create a virtual environment and install dependencies.**

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements-dev.txt
   ```

3. **Start the backing services.** This starts Postgres and Redis in containers:

   ```bash
   docker compose up -d db redis
   ```

   Wait until both containers report `healthy`:

   ```bash
   docker compose ps
   ```

4. **Configure your environment.**
   - Copy `.env.example` to `.env`
   - Set `DATABASE_URL` to `postgresql://dev:dev@localhost:5432/service`
   - Leave `FEATURE_FLAGS` empty unless you need a specific flag

5. **Run the migrations and start the server.**

   ```bash
   make migrate
   make run
   ```

   The server listens on <http://localhost:8000>.

## Troubleshooting

**Port 5432 is already in use.** Another Postgres is running. Stop it, or change
the port mapping in `docker-compose.yml`.

**`pip install` fails on `psycopg`.** Install the Postgres client headers:

- macOS: `brew install libpq`
- Debian/Ubuntu: `sudo apt install libpq-dev`

> **Tip:** run `make doctor` to check every prerequisite at once.

## Next steps

- Read the [architecture overview](https://example.com/arch)
- Pick up a `good-first-issue` ticket
