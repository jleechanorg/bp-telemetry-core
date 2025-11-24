# Blueplane Telemetry Core - Docker Infrastructure

This directory contains Docker configuration files for running Blueplane Telemetry Core in containers.

## Files

- **Dockerfile.server**: Multi-stage Docker image for the processing server
- **docker-compose.yml**: Orchestration configuration for Redis + Processing Server

## Quick Start

### Prerequisites

- Docker Desktop 4.0+ installed and running
- macOS 11+ (Big Sur or later)
- 2GB available disk space
- 4GB RAM minimum (8GB recommended)

### Starting Services

```bash
# From repository root
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f

# View specific service logs
docker-compose logs -f blueplane-server
docker-compose logs -f redis
```

### Stopping Services

```bash
# Stop services (keeps data)
docker-compose stop

# Stop and remove containers (keeps data volumes)
docker-compose down

# Stop and remove everything including volumes
docker-compose down -v
```

## Services

### Redis

- **Image**: redis:7-alpine
- **Port**: 6379
- **Purpose**: Message queue (Streams) and metrics storage
- **Data**: Persisted in named volume `blueplane-redis-data`
- **Configuration**: AOF persistence enabled

### Processing Server

- **Image**: Built from Dockerfile.server
- **Base**: python:3.11-slim
- **Purpose**: Event processing and telemetry analysis
- **Entry Point**: `bp-server` command

## Volume Mounts

The processing server requires access to several host directories:

### Required Mounts

| Host Path | Container Path | Mode | Purpose |
|-----------|---------------|------|---------|
| `~/.blueplane` | `/data/blueplane` | rw | Data storage and configuration |
| `~/.claude/projects` | `/capture/claude/projects` | ro | Claude Code transcript monitoring |
| `~/Library/Application Support/Cursor` | `/capture/cursor` | ro | Cursor database monitoring |

### Optional Mounts

| Host Path | Container Path | Mode | Purpose |
|-----------|---------------|------|---------|
| `~/Dev` (configurable) | `/workspace` | ro | Workspace directory access |

### Configuring Paths

Set environment variables before running `docker-compose up`:

```bash
# Example: Custom paths
export BLUEPLANE_DATA_DIR=~/custom/blueplane
export WORKSPACE_DIR=~/Projects
docker-compose up -d
```

Or create a `.env` file:

```bash
# .env file in repository root
BLUEPLANE_DATA_DIR=/Users/yourname/custom/blueplane
WORKSPACE_DIR=/Users/yourname/Projects
LOG_LEVEL=DEBUG
```

## Environment Variables

### Redis Connection

- `REDIS_HOST`: Redis hostname (default: `redis`)
- `REDIS_PORT`: Redis port (default: `6379`)

### Data Directories

- `BLUEPLANE_DATA_DIR`: Data storage location (default: `~/.blueplane`)
- `CLAUDE_PROJECTS_DIR`: Claude Code projects directory
- `CURSOR_DATA_DIR`: Cursor application data directory
- `WORKSPACE_ROOT`: Workspace root directory

### Logging

- `LOG_LEVEL`: Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) (default: `INFO`)
- `PYTHONUNBUFFERED`: Enable unbuffered Python output (default: `1`)

## Health Checks

Both services include health checks:

- **Redis**: `redis-cli ping` every 5s
- **Processing Server**: Process check every 30s

Check health status:

```bash
docker-compose ps
```

## Networking

Services communicate on the `blueplane-network` bridge network:

- Redis is accessible at `redis:6379` from the processing server
- Port 6379 is exposed to the host for debugging (optional)

## Resource Limits

Optional resource limits are commented out in `docker-compose.yml`. Uncomment and adjust based on your system:

```yaml
deploy:
  resources:
    limits:
      cpus: '2.0'
      memory: 2G
    reservations:
      cpus: '0.5'
      memory: 512M
```

## Troubleshooting

### Services won't start

```bash
# Check logs
docker-compose logs

# Restart services
docker-compose restart

# Rebuild images
docker-compose build --no-cache
docker-compose up -d
```

### Permission errors

Ensure the user inside the container (UID 1000) has access to mounted volumes:

```bash
# Check ownership
ls -la ~/.blueplane

# Fix if needed
chown -R 1000:1000 ~/.blueplane
```

### Redis connection errors

```bash
# Test Redis connectivity
docker-compose exec blueplane-server redis-cli -h redis ping

# Should return: PONG
```

### Viewing database

```bash
# Access SQLite database
docker-compose exec blueplane-server sqlite3 /data/blueplane/telemetry.db

# View tables
.tables

# Exit SQLite
.exit
```

## Development

### Building Images Locally

```bash
# Build without cache
docker-compose build --no-cache

# Build specific service
docker-compose build blueplane-server
```

### Accessing Containers

```bash
# Shell into processing server
docker-compose exec blueplane-server /bin/bash

# Shell into Redis
docker-compose exec redis redis-cli
```

### Testing Changes

```bash
# Restart after code changes
docker-compose restart blueplane-server

# Or rebuild and restart
docker-compose up -d --build blueplane-server
```

## Security Notes

- Services run as non-root user (UID 1000)
- Read-only mounts for captured data
- No privileged containers
- Network isolation via bridge network

## See Also

- [PACKAGING_SPEC.md](../docs/PACKAGING_SPEC.md) - Full packaging specification
- [ARCHITECTURE.md](../docs/ARCHITECTURE.md) - System architecture overview
- [README.md](../README.md) - Main project README
