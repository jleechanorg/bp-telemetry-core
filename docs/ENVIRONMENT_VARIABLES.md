# Blueplane Telemetry Core - Environment Variables

This document lists all environment variables supported by Blueplane Telemetry Core.

## Quick Reference

```bash
# Configuration
BP_CONFIG_PATH              # Config directory or file path
BP_CONFIG_MODE              # Configuration mode (main/debug)

# Paths
BP_DATA_DIR                 # Data storage directory
WORKSPACE_DIR               # Workspace root directory
CLAUDE_PROJECTS_DIR         # Claude Code projects directory
CURSOR_DATA_DIR             # Cursor data directory

# Redis
REDIS_HOST                  # Redis server hostname
REDIS_PORT                  # Redis server port
REDIS_DB                    # Redis database number

# Database
SQLITE_PATH                 # SQLite database path
BP_DATABASE_PATH            # Alternative SQLite path

# Logging
LOG_LEVEL                   # Logging level (DEBUG, INFO, WARNING, ERROR)
BP_LOG_LEVEL                # Alternative log level
BP_LOG_FORMAT               # Log format (json/text)

# Debug
BP_DEBUG                    # Enable debug mode
BP_VERBOSE                  # Enable verbose output
```

## Complete Reference

### Configuration

#### `BP_CONFIG_PATH`
- **Description**: Path to configuration directory or specific config file
- **Default**: Searches `~/.blueplane`, `./config`, `/etc/blueplane`
- **Type**: string (path)
- **Example**: `BP_CONFIG_PATH=/etc/blueplane`
- **Example**: `BP_CONFIG_PATH=~/.blueplane/custom.yaml`

#### `BP_CONFIG_MODE`
- **Description**: Configuration mode to use
- **Default**: `main`
- **Type**: string (`main` or `debug`)
- **Example**: `BP_CONFIG_MODE=debug`
- **Notes**: Debug mode enables enhanced logging and debugging features

---

### Paths and Directories

#### `BP_DATA_DIR` / `BLUEPLANE_DATA_DIR`
- **Description**: Primary data storage directory (database, logs, cache)
- **Default**: `~/.blueplane`
- **Type**: string (path)
- **Example**: `BP_DATA_DIR=/var/lib/blueplane`
- **Example**: `BLUEPLANE_DATA_DIR=~/.blueplane`
- **Notes**: Automatically expanded for `~` and environment variables

#### `WORKSPACE_DIR` / `WORKSPACE_ROOT`
- **Description**: Root directory for workspace/project monitoring
- **Default**: `~/Dev`
- **Type**: string (path)
- **Example**: `WORKSPACE_DIR=~/Projects`
- **Example**: `WORKSPACE_ROOT=/home/user/code`
- **Notes**: Used by processing server to access code files

#### `CLAUDE_PROJECTS_DIR`
- **Description**: Claude Code projects directory for transcript monitoring
- **Default**: `~/.claude/projects`
- **Type**: string (path)
- **Example**: `CLAUDE_PROJECTS_DIR=~/.claude/projects`
- **Notes**: Location of Claude Code JSONL transcript files

#### `CURSOR_DATA_DIR`
- **Description**: Cursor application data directory
- **Default**: `~/Library/Application Support/Cursor` (macOS)
- **Type**: string (path)
- **Example**: `CURSOR_DATA_DIR=~/Library/Application Support/Cursor`
- **Notes**: Platform-specific; contains `state.vscdb` database

---

### Redis Configuration

#### `REDIS_HOST`
- **Description**: Redis server hostname or IP address
- **Default**: `localhost`
- **Type**: string (hostname)
- **Example**: `REDIS_HOST=redis.example.com`
- **Example**: `REDIS_HOST=127.0.0.1`
- **Notes**: In Docker, typically set to `redis` (service name)

#### `REDIS_PORT`
- **Description**: Redis server port
- **Default**: `6379`
- **Type**: integer
- **Example**: `REDIS_PORT=6379`
- **Notes**: Standard Redis port

#### `REDIS_DB`
- **Description**: Redis database number
- **Default**: `0`
- **Type**: integer (0-15)
- **Example**: `REDIS_DB=0`
- **Notes**: Redis supports 16 databases (0-15)

#### `REDIS_PASSWORD`
- **Description**: Redis authentication password
- **Default**: none
- **Type**: string
- **Example**: `REDIS_PASSWORD=secretpassword`
- **Notes**: Only needed if Redis requires authentication

#### `REDIS_TIMEOUT`
- **Description**: Redis connection timeout in seconds
- **Default**: `5.0`
- **Type**: float
- **Example**: `REDIS_TIMEOUT=10.0`
- **Notes**: Increase for slow networks

---

### Database Configuration

#### `SQLITE_PATH` / `BP_DATABASE_PATH`
- **Description**: Path to SQLite database file
- **Default**: `~/.blueplane/telemetry.db`
- **Type**: string (path)
- **Example**: `SQLITE_PATH=/var/lib/blueplane/telemetry.db`
- **Example**: `BP_DATABASE_PATH=~/blueplane.db`
- **Notes**: Database will be created if it doesn't exist

#### `SQLITE_BUSY_TIMEOUT`
- **Description**: SQLite busy timeout in milliseconds
- **Default**: `5000`
- **Type**: integer
- **Example**: `SQLITE_BUSY_TIMEOUT=10000`
- **Notes**: How long to wait for locked database

#### `BP_DB_COMPRESSION`
- **Description**: Enable database compression for raw traces
- **Default**: `true`
- **Type**: boolean (`true`/`false`)
- **Example**: `BP_DB_COMPRESSION=false`
- **Notes**: Disabling improves speed but increases disk usage

#### `BP_DB_COMPRESSION_LEVEL`
- **Description**: Compression level (zlib)
- **Default**: `6`
- **Type**: integer (1-9)
- **Example**: `BP_DB_COMPRESSION_LEVEL=9`
- **Notes**: Higher = better compression but slower

---

### Logging

#### `LOG_LEVEL` / `BP_LOG_LEVEL`
- **Description**: Logging level
- **Default**: `INFO`
- **Type**: string (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`)
- **Example**: `LOG_LEVEL=DEBUG`
- **Example**: `BP_LOG_LEVEL=WARNING`
- **Notes**: `DEBUG` is very verbose; use for troubleshooting only

#### `BP_LOG_FORMAT`
- **Description**: Log output format
- **Default**: `json`
- **Type**: string (`json` or `text`)
- **Example**: `BP_LOG_FORMAT=text`
- **Notes**: JSON is machine-readable; text is human-readable

#### `BP_LOG_FILE`
- **Description**: Path to log file
- **Default**: `~/.blueplane/logs/blueplane.log`
- **Type**: string (path)
- **Example**: `BP_LOG_FILE=/var/log/blueplane/server.log`
- **Notes**: Parent directory must exist

#### `BP_LOG_CONSOLE`
- **Description**: Enable console (stdout) logging
- **Default**: `true`
- **Type**: boolean
- **Example**: `BP_LOG_CONSOLE=false`
- **Notes**: Useful to disable in Docker with file logging

---

### Processing Pipeline

#### `BP_FAST_PATH_ENABLED`
- **Description**: Enable fast path processing
- **Default**: `true`
- **Type**: boolean
- **Example**: `BP_FAST_PATH_ENABLED=false`
- **Notes**: Disabling stops event ingestion

#### `BP_FAST_PATH_BATCH_SIZE`
- **Description**: Number of events per batch
- **Default**: `100`
- **Type**: integer
- **Example**: `BP_FAST_PATH_BATCH_SIZE=50`
- **Notes**: Smaller = lower latency, larger = better throughput

#### `BP_SLOW_PATH_ENABLED`
- **Description**: Enable slow path async workers
- **Default**: `true`
- **Type**: boolean
- **Example**: `BP_SLOW_PATH_ENABLED=false`
- **Notes**: Disabling stops metrics and conversation processing

#### `BP_METRICS_WORKERS`
- **Description**: Number of metrics worker processes
- **Default**: `2`
- **Type**: integer
- **Example**: `BP_METRICS_WORKERS=4`
- **Notes**: More workers = faster metrics but more CPU

#### `BP_CONVERSATION_WORKERS`
- **Description**: Number of conversation worker processes
- **Default**: `2`
- **Type**: integer
- **Example**: `BP_CONVERSATION_WORKERS=1`
- **Notes**: Usually 1-2 is sufficient

---

### Platform Support

#### `BP_CLAUDE_SUPPORT`
- **Description**: Enable Claude Code platform support
- **Default**: `true`
- **Type**: boolean
- **Example**: `BP_CLAUDE_SUPPORT=false`
- **Notes**: Disable if not using Claude Code

#### `BP_CURSOR_SUPPORT`
- **Description**: Enable Cursor platform support
- **Default**: `true`
- **Type**: boolean
- **Example**: `BP_CURSOR_SUPPORT=false`
- **Notes**: Disable if not using Cursor

#### `BP_CLAUDE_POLL_INTERVAL`
- **Description**: Claude transcript poll interval in seconds
- **Default**: `5`
- **Type**: integer
- **Example**: `BP_CLAUDE_POLL_INTERVAL=10`
- **Notes**: Lower = more CPU, higher = higher latency

#### `BP_CURSOR_POLL_INTERVAL`
- **Description**: Cursor database poll interval in seconds
- **Default**: `30`
- **Type**: integer
- **Example**: `BP_CURSOR_POLL_INTERVAL=60`
- **Notes**: Cursor updates less frequently than Claude

---

### Privacy Settings

#### `BP_PRIVACY_MODE`
- **Description**: Privacy mode
- **Default**: `strict`
- **Type**: string (`strict`, `balanced`, `development`)
- **Example**: `BP_PRIVACY_MODE=balanced`
- **Notes**: `strict` = maximum privacy, `development` = more data for debugging

#### `BP_HASH_FILE_PATHS`
- **Description**: Hash file paths instead of storing them
- **Default**: `true`
- **Type**: boolean
- **Example**: `BP_HASH_FILE_PATHS=false`
- **Notes**: Disabling may expose file structure

#### `BP_HASH_WORKSPACE`
- **Description**: Hash workspace names
- **Default**: `true`
- **Type**: boolean
- **Example**: `BP_HASH_WORKSPACE=false`
- **Notes**: For privacy in multi-user systems

---

### Monitoring and Health

#### `BP_HEALTH_CHECKS_ENABLED`
- **Description**: Enable health checks
- **Default**: `true`
- **Type**: boolean
- **Example**: `BP_HEALTH_CHECKS_ENABLED=false`
- **Notes**: Health checks monitor system status

#### `BP_HEALTH_CHECK_INTERVAL`
- **Description**: Health check interval in seconds
- **Default**: `60`
- **Type**: integer
- **Example**: `BP_HEALTH_CHECK_INTERVAL=30`
- **Notes**: More frequent = earlier problem detection

#### `BP_QUEUE_WARNING_THRESHOLD`
- **Description**: Queue depth warning threshold
- **Default**: `5000`
- **Type**: integer
- **Example**: `BP_QUEUE_WARNING_THRESHOLD=10000`
- **Notes**: Warning when queue exceeds this size

#### `BP_QUEUE_CRITICAL_THRESHOLD`
- **Description**: Queue depth critical threshold
- **Default**: `8000`
- **Type**: integer
- **Example**: `BP_QUEUE_CRITICAL_THRESHOLD=15000`
- **Notes**: Critical alert when exceeded

---

### Feature Flags

#### `BP_METRICS_ENABLED`
- **Description**: Enable metrics derivation
- **Default**: `true`
- **Type**: boolean
- **Example**: `BP_METRICS_ENABLED=false`

#### `BP_CONVERSATIONS_ENABLED`
- **Description**: Enable conversation reconstruction
- **Default**: `true`
- **Type**: boolean
- **Example**: `BP_CONVERSATIONS_ENABLED=false`

#### `BP_AI_INSIGHTS_ENABLED`
- **Description**: Enable AI insights (experimental)
- **Default**: `false`
- **Type**: boolean
- **Example**: `BP_AI_INSIGHTS_ENABLED=true`
- **Notes**: Experimental feature, may change

#### `BP_CLI_ENABLED`
- **Description**: Enable CLI interface
- **Default**: `true`
- **Type**: boolean
- **Example**: `BP_CLI_ENABLED=false`

---

### Development and Debugging

#### `BP_DEBUG`
- **Description**: Enable debug mode
- **Default**: `false`
- **Type**: boolean
- **Example**: `BP_DEBUG=true`
- **Notes**: Enables verbose logging and debug features

#### `BP_VERBOSE`
- **Description**: Enable verbose output
- **Default**: `false`
- **Type**: boolean
- **Example**: `BP_VERBOSE=true`
- **Notes**: More detailed console output

#### `BP_PROFILE`
- **Description**: Enable performance profiling
- **Default**: `false`
- **Type**: boolean
- **Example**: `BP_PROFILE=true`
- **Notes**: Creates profile data for analysis

#### `BP_TEST_MODE`
- **Description**: Enable test mode
- **Default**: `false`
- **Type**: boolean
- **Example**: `BP_TEST_MODE=true`
- **Notes**: For automated testing

#### `BP_DUMP_EVENTS`
- **Description**: Dump events to disk for inspection
- **Default**: `false`
- **Type**: boolean
- **Example**: `BP_DUMP_EVENTS=true`
- **Notes**: Debug feature; increases disk usage

#### `BP_EVENT_DUMP_DIR`
- **Description**: Directory for event dumps
- **Default**: `~/.blueplane/debug/events`
- **Type**: string (path)
- **Example**: `BP_EVENT_DUMP_DIR=/tmp/events`
- **Notes**: Used when `BP_DUMP_EVENTS=true`

---

### Python Settings

#### `PYTHONUNBUFFERED`
- **Description**: Disable Python output buffering
- **Default**: `1` (enabled)
- **Type**: integer (0 or 1)
- **Example**: `PYTHONUNBUFFERED=1`
- **Notes**: Recommended for Docker containers

#### `PYTHONDONTWRITEBYTECODE`
- **Description**: Don't write .pyc bytecode files
- **Default**: `0` (write bytecode)
- **Type**: integer (0 or 1)
- **Example**: `PYTHONDONTWRITEBYTECODE=1`
- **Notes**: Cleaner in development

#### `PYTHONOPTIMIZE`
- **Description**: Python optimization level
- **Default**: `0` (no optimization)
- **Type**: integer (0, 1, 2)
- **Example**: `PYTHONOPTIMIZE=1`
- **Notes**: `2` removes docstrings

---

## Usage Examples

### Development Setup

```bash
# .env file for development
BP_CONFIG_MODE=debug
LOG_LEVEL=DEBUG
BP_DEBUG=true
WORKSPACE_DIR=~/projects
BP_HASH_FILE_PATHS=false
BP_PRIVACY_MODE=development
```

### Production Setup

```bash
# .env file for production
BP_DATA_DIR=/var/lib/blueplane
LOG_LEVEL=INFO
BP_LOG_FORMAT=json
BP_LOG_FILE=/var/log/blueplane/server.log
WORKSPACE_DIR=/data/workspaces
BP_PRIVACY_MODE=strict
```

### Docker Setup

```bash
# docker-compose.yml or .env for Docker
REDIS_HOST=redis
BP_DATA_DIR=/data/blueplane
CLAUDE_PROJECTS_DIR=/capture/claude/projects
CURSOR_DATA_DIR=/capture/cursor
WORKSPACE_ROOT=/workspace
PYTHONUNBUFFERED=1
```

### Minimal Setup

```bash
# Bare minimum - uses all defaults
WORKSPACE_DIR=~/Projects
```

## Integration with Configuration System

Environment variables override YAML configuration values:

1. **Default values** (in code)
2. **YAML configuration** (main.yaml or debug.yaml)
3. **Environment variables** (highest priority)
4. **Command-line arguments** (if supported)

Example precedence:

```yaml
# config/main.yaml
logging:
  level: INFO

# Environment variable overrides YAML
LOG_LEVEL=DEBUG

# Result: DEBUG (environment variable wins)
```

## Security Best Practices

1. **Never commit `.env` files** to version control
2. **Use `.env.template`** for documentation
3. **Protect sensitive values**: Use environment variables, not config files
4. **Set proper permissions**: `chmod 600 .env`
5. **Use secrets management** in production (Vault, AWS Secrets Manager, etc.)

## Troubleshooting

### Variable not taking effect

1. Verify variable is exported: `echo $VARIABLE_NAME`
2. Check spelling and capitalization
3. Restart the application after setting variables
4. Check configuration loading order

### Path not found

1. Ensure paths are absolute or properly expanded
2. Use quotes for paths with spaces: `"/path/with spaces"`
3. Check file/directory permissions

### Boolean values

Use `true`/`false` (lowercase) for boolean environment variables:
- ✅ `BP_DEBUG=true`
- ✅ `BP_DEBUG=false`
- ❌ `BP_DEBUG=True`
- ❌ `BP_DEBUG=1` (may work but not recommended)

## See Also

- [Configuration System](../config/README.md)
- [PACKAGING_SPEC.md](./PACKAGING_SPEC.md)
- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [.env.template](../.env.template)
