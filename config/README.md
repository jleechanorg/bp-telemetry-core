# Blueplane Telemetry Core - Configuration

This directory contains YAML configuration files for Blueplane Telemetry Core.

## Configuration Files

### main.yaml
Primary configuration file for production use. Contains settings for:
- System paths and directories
- Redis connection and streams
- Database configuration
- Processing pipeline
- Privacy settings
- Monitoring and logging
- Feature flags

### debug.yaml
Debug configuration extending main.yaml. Includes:
- Enhanced logging (DEBUG level)
- Smaller batch sizes for easier debugging
- More frequent polling and health checks
- Disabled compression for data inspection
- Test mode settings
- Profiling and error tracking

### redis.yaml
Legacy Redis-specific configuration (superseded by main.yaml).

### privacy.yaml
Legacy privacy configuration (superseded by main.yaml).

### cursor.yaml
Cursor-specific platform configuration.

## Using Configuration

### Default Configuration

By default, Blueplane uses `main.yaml`:

```bash
bp-server
```

### Debug Mode

Use debug configuration:

```bash
BP_CONFIG_MODE=debug bp-server
# or
export BP_CONFIG_MODE=debug
bp-server
```

### Custom Configuration Path

Specify custom configuration directory:

```bash
BP_CONFIG_PATH=/path/to/config bp-server
```

### Custom Configuration File

Use a specific configuration file:

```bash
bp-server --config /path/to/custom.yaml
```

## Environment Variable Overrides

Many configuration values can be overridden with environment variables.
This is useful for Docker containers, CI/CD, and deployment-specific settings.

### Common Overrides

```bash
# Data directory
export BP_DATA_DIR=~/.blueplane
export BLUEPLANE_DATA_DIR=~/.blueplane  # Alternative

# Workspace directory
export WORKSPACE_DIR=~/Dev
export WORKSPACE_ROOT=~/Dev  # Alternative

# Redis connection
export REDIS_HOST=localhost
export REDIS_PORT=6379
export REDIS_DB=0

# Database
export SQLITE_PATH=~/.blueplane/telemetry.db
export BP_DATABASE_PATH=~/.blueplane/telemetry.db  # Alternative

# Logging
export LOG_LEVEL=INFO
export BP_LOG_LEVEL=DEBUG  # Alternative

# Configuration mode
export BP_CONFIG_MODE=debug  # main or debug
```

### Complete List

See [Environment Variables Documentation](../docs/ENVIRONMENT_VARIABLES.md) for complete list.

## Configuration Loading Order

Blueplane loads configuration in this order (later sources override earlier):

1. **Default values** - Built-in defaults in Python code
2. **YAML file** - Configuration from `main.yaml` or `debug.yaml`
3. **Environment variables** - Override specific values
4. **Command-line arguments** - Highest priority (where available)

## Configuration Locations

Blueplane searches for configuration in these locations (in order):

1. **Current directory** - `./config/`
2. **User home** - `~/.blueplane/`
3. **Repository root** - `<repo>/config/` (for development)
4. **System-wide** - `/etc/blueplane/`

## Validation

Configuration is validated on startup. Invalid values will cause the server to fail with clear error messages.

```bash
# Test configuration without starting server
bp config validate

# Show loaded configuration
bp config show
```

## Creating Custom Configurations

### 1. Copy Template

```bash
cp config/main.yaml ~/.blueplane/custom.yaml
```

### 2. Edit Settings

Edit `custom.yaml` with your preferred text editor.

### 3. Use Custom Configuration

```bash
BP_CONFIG_PATH=~/.blueplane bp-server
# or
bp-server --config ~/.blueplane/custom.yaml
```

## Docker Configuration

When running in Docker, configuration is handled through:

1. **Volume mounts** - Mount custom config directory:
   ```bash
   docker-compose run -v ~/.blueplane:/data/blueplane blueplane-server
   ```

2. **Environment variables** - Pass via docker-compose.yml or command line:
   ```yaml
   environment:
     - LOG_LEVEL=DEBUG
     - REDIS_HOST=redis
   ```

3. **Build-time** - Copy config into image (not recommended for secrets)

## Security Notes

- **Never commit secrets** to configuration files
- Use **environment variables** for sensitive values (API keys, passwords)
- Set appropriate **file permissions**: `chmod 600 ~/.blueplane/*.yaml`
- Use **~/.blueplane** (user directory) for personal configurations
- Use **/etc/blueplane** for system-wide configurations (root-owned)

## Troubleshooting

### Configuration not found

```
Error: Configuration file not found
```

**Solution**: Check configuration locations or set `BP_CONFIG_PATH`

### Invalid YAML syntax

```
Error: Invalid YAML in config/main.yaml
```

**Solution**: Validate YAML syntax with `yamllint` or online tools

### Environment variable not working

1. Check variable name matches documentation
2. Verify environment variable is exported
3. Check configuration loading order

### Values not being overridden

Configuration precedence: CLI args > env vars > YAML > defaults

## Examples

### Production Setup

```yaml
# ~/.blueplane/main.yaml
paths:
  data_dir: "/var/lib/blueplane"
  workspace_dir: "/home/user/projects"

redis:
  host: "redis.example.com"
  port: 6379

logging:
  level: "INFO"
  handlers:
    file:
      path: "/var/log/blueplane/server.log"
```

### Development Setup

```yaml
# config/dev.yaml
paths:
  data_dir: "./data"
  workspace_dir: "."

logging:
  level: "DEBUG"
  format: "text"

features:
  ai_insights_enabled: true
```

### Docker Setup

```yaml
# docker-compose.yml environment
environment:
  - BP_DATA_DIR=/data/blueplane
  - REDIS_HOST=redis
  - LOG_LEVEL=INFO
  - WORKSPACE_DIR=/workspace
```

## See Also

- [Environment Variables](../docs/ENVIRONMENT_VARIABLES.md)
- [PACKAGING_SPEC.md](../docs/PACKAGING_SPEC.md)
- [ARCHITECTURE.md](../docs/ARCHITECTURE.md)
