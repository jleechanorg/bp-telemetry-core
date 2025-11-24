# Copyright © 2025 Sierra Labs LLC
# SPDX-License-Identifier: AGPL-3.0-only
# License-Filename: LICENSE

"""
Configuration management for Blueplane Telemetry Core.

Loads configuration from YAML files and environment variables.
Provides typed configuration classes with validation.
"""

import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field


# =============================================================================
# Configuration Data Classes
# =============================================================================

@dataclass
class PathsConfig:
    """System paths configuration."""
    data_dir: str = "~/.blueplane"
    workspace_dir: str = "~/Dev"
    claude_projects_dir: str = "~/.claude/projects"
    cursor_data_dir: str = "~/Library/Application Support/Cursor"

    def __post_init__(self):
        """Expand paths."""
        self.data_dir = str(Path(self.data_dir).expanduser())
        self.workspace_dir = str(Path(self.workspace_dir).expanduser())
        self.claude_projects_dir = str(Path(self.claude_projects_dir).expanduser())
        self.cursor_data_dir = str(Path(self.cursor_data_dir).expanduser())


@dataclass
class RedisConnectionConfig:
    """Redis connection configuration."""
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    max_connections: int = 10
    socket_timeout: float = 5.0
    socket_connect_timeout: float = 2.0
    retry_on_timeout: bool = True
    health_check_interval: int = 30


@dataclass
class StreamConfig:
    """Redis Stream configuration."""
    name: str
    consumer_group: str
    consumer_name_prefix: str = "consumer"
    max_length: int = 10000
    trim_approximate: bool = True
    block_ms: int = 1000
    count: int = 100
    retry_timeout_ms: int = 300000


@dataclass
class StreamsConfig:
    """All streams configuration."""
    message_queue: StreamConfig
    dlq: StreamConfig
    cdc: StreamConfig

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'StreamsConfig':
        """Create from dictionary."""
        return cls(
            message_queue=StreamConfig(**data.get('message_queue', {})),
            dlq=StreamConfig(**data.get('dlq', {})),
            cdc=StreamConfig(**data.get('cdc', {}))
        )


@dataclass
class SQLiteConfig:
    """SQLite database configuration."""
    journal_mode: str = "WAL"
    synchronous: str = "NORMAL"
    cache_size: int = 10000
    temp_store: str = "MEMORY"
    busy_timeout: int = 5000


@dataclass
class CompressionConfig:
    """Data compression configuration."""
    enabled: bool = True
    algorithm: str = "zlib"
    level: int = 6


@dataclass
class RetentionConfig:
    """Data retention configuration."""
    raw_traces_days: int = 90
    conversations_days: int = 365
    metrics_days: int = 90


@dataclass
class DatabaseConfig:
    """Database configuration."""
    sqlite_path: str = "~/.blueplane/telemetry.db"
    sqlite: SQLiteConfig = field(default_factory=SQLiteConfig)
    compression: CompressionConfig = field(default_factory=CompressionConfig)
    retention: RetentionConfig = field(default_factory=RetentionConfig)

    def __post_init__(self):
        """Expand paths."""
        self.sqlite_path = str(Path(self.sqlite_path).expanduser())


@dataclass
class FastPathConfig:
    """Fast path processing configuration."""
    enabled: bool = True
    batch_size: int = 100
    batch_timeout_ms: int = 100
    max_queue_size: int = 10000
    log_every_batch: bool = False


@dataclass
class WorkerConfig:
    """Worker configuration."""
    count: int = 2
    batch_size: int = 10
    log_every_event: bool = False


@dataclass
class SlowPathConfig:
    """Slow path processing configuration."""
    enabled: bool = True
    metrics_worker: WorkerConfig = field(default_factory=WorkerConfig)
    conversations_worker: WorkerConfig = field(default_factory=WorkerConfig)
    insights_worker: WorkerConfig = field(default_factory=lambda: WorkerConfig(count=1, batch_size=5))


@dataclass
class ProcessingConfig:
    """Processing pipeline configuration."""
    fast_path: FastPathConfig = field(default_factory=FastPathConfig)
    slow_path: SlowPathConfig = field(default_factory=SlowPathConfig)


@dataclass
class PrivacyConfig:
    """Privacy settings configuration."""
    mode: str = "strict"  # strict, balanced, development
    hash_file_paths: bool = True
    hash_workspace: bool = True
    hash_algorithm: str = "sha256"
    hash_truncate_length: int = 16
    opt_out: List[str] = field(default_factory=list)


@dataclass
class MonitoringConfig:
    """Monitoring and health check configuration."""
    enabled: bool = True
    health_check_interval_seconds: int = 60
    queue_depth_warning_threshold: int = 5000
    queue_depth_critical_threshold: int = 8000
    lag_warning_ms: int = 10000
    lag_critical_ms: int = 60000


@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str = "INFO"
    format: str = "json"  # json or text
    include_context: bool = True
    include_timestamps: bool = True


@dataclass
class FeaturesConfig:
    """Feature flags configuration."""
    fast_path_enabled: bool = True
    slow_path_enabled: bool = True
    metrics_derivation_enabled: bool = True
    conversation_reconstruction_enabled: bool = True
    ai_insights_enabled: bool = False
    claude_code_support: bool = True
    cursor_support: bool = True
    cli_enabled: bool = True


# =============================================================================
# Main Configuration Class
# =============================================================================

@dataclass
class BlueplaneConfig:
    """
    Main configuration class for Blueplane Telemetry Core.

    This class aggregates all configuration sections and provides
    methods for loading from YAML files and environment variables.
    """
    version: str = "1.0"
    paths: PathsConfig = field(default_factory=PathsConfig)
    redis: RedisConnectionConfig = field(default_factory=RedisConnectionConfig)
    streams: Optional[StreamsConfig] = None
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)
    privacy: PrivacyConfig = field(default_factory=PrivacyConfig)
    monitoring: MonitoringConfig = field(default_factory=MonitoringConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    features: FeaturesConfig = field(default_factory=FeaturesConfig)

    @classmethod
    def load(cls, config_path: Optional[Path] = None, mode: str = "main") -> 'BlueplaneConfig':
        """
        Load configuration from YAML file with environment variable overrides.

        Args:
            config_path: Path to configuration directory or file.
                        If None, searches standard locations.
            mode: Configuration mode ('main' or 'debug')

        Returns:
            BlueplaneConfig instance
        """
        # Find config directory
        if config_path is None:
            config_path = cls._find_config_dir()
        elif config_path.is_file():
            config_dir = config_path.parent
            config_file = config_path
        else:
            config_dir = config_path
            config_file = config_dir / f"{mode}.yaml"

        # Load YAML configuration
        if config_file and config_file.exists():
            with open(config_file, 'r') as f:
                config_data = yaml.safe_load(f) or {}
        else:
            config_data = {}

        # Apply environment variable overrides
        config_data = cls._apply_env_overrides(config_data)

        # Create configuration instance
        return cls._from_dict(config_data)

    @classmethod
    def _find_config_dir(cls) -> Path:
        """Find configuration directory in standard locations."""
        possible_locations = [
            Path.home() / ".blueplane",
            Path(__file__).parent.parent.parent / "config",
            Path("/etc/blueplane"),
        ]

        # Also check relative to current working directory
        cwd_config = Path.cwd() / "config"
        if cwd_config.exists():
            possible_locations.insert(0, cwd_config)

        for location in possible_locations:
            if location.exists() and location.is_dir():
                yaml_files = list(location.glob("*.yaml")) + list(location.glob("*.yml"))
                if yaml_files:
                    return location

        # Default to ~/.blueplane
        return Path.home() / ".blueplane"

    @classmethod
    def _apply_env_overrides(cls, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply environment variable overrides to configuration."""
        # Paths
        if 'paths' not in config_data:
            config_data['paths'] = {}

        config_data['paths']['data_dir'] = os.getenv(
            'BP_DATA_DIR',
            os.getenv('BLUEPLANE_DATA_DIR', config_data['paths'].get('data_dir', '~/.blueplane'))
        )
        config_data['paths']['workspace_dir'] = os.getenv(
            'WORKSPACE_DIR',
            os.getenv('WORKSPACE_ROOT', config_data['paths'].get('workspace_dir', '~/Dev'))
        )

        # Redis
        if 'redis' not in config_data:
            config_data['redis'] = {}

        config_data['redis']['host'] = os.getenv(
            'REDIS_HOST',
            config_data['redis'].get('host', 'localhost')
        )
        config_data['redis']['port'] = int(os.getenv(
            'REDIS_PORT',
            str(config_data['redis'].get('port', 6379))
        ))
        config_data['redis']['db'] = int(os.getenv(
            'REDIS_DB',
            str(config_data['redis'].get('db', 0))
        ))

        # Logging
        if 'logging' not in config_data:
            config_data['logging'] = {}

        config_data['logging']['level'] = os.getenv(
            'LOG_LEVEL',
            os.getenv('BP_LOG_LEVEL', config_data['logging'].get('level', 'INFO'))
        )

        # Database
        if 'database' not in config_data:
            config_data['database'] = {}

        config_data['database']['sqlite_path'] = os.getenv(
            'SQLITE_PATH',
            os.getenv('BP_DATABASE_PATH', config_data['database'].get('sqlite_path', '~/.blueplane/telemetry.db'))
        )

        return config_data

    @classmethod
    def _from_dict(cls, data: Dict[str, Any]) -> 'BlueplaneConfig':
        """Create BlueplaneConfig from dictionary."""
        return cls(
            version=data.get('version', '1.0'),
            paths=PathsConfig(**data.get('paths', {})),
            redis=RedisConnectionConfig(**data.get('redis', {}).get('connection_pool', data.get('redis', {}))),
            streams=StreamsConfig.from_dict(data.get('streams', {})) if 'streams' in data else None,
            database=DatabaseConfig(
                sqlite_path=data.get('database', {}).get('sqlite_path', '~/.blueplane/telemetry.db'),
                sqlite=SQLiteConfig(**data.get('database', {}).get('sqlite', {})),
                compression=CompressionConfig(**data.get('database', {}).get('compression', {})),
                retention=RetentionConfig(**data.get('database', {}).get('retention', {}))
            ),
            processing=ProcessingConfig(
                fast_path=FastPathConfig(**data.get('processing', {}).get('fast_path', {})),
                slow_path=SlowPathConfig(**data.get('processing', {}).get('slow_path', {}))
            ),
            privacy=PrivacyConfig(**data.get('privacy', {})),
            monitoring=MonitoringConfig(**data.get('monitoring', {})),
            logging=LoggingConfig(**data.get('logging', {})),
            features=FeaturesConfig(**data.get('features', {}))
        )


# =============================================================================
# Convenience Functions
# =============================================================================

def load_config(config_path: Optional[Path] = None, mode: str = "main") -> BlueplaneConfig:
    """
    Load Blueplane configuration.

    Args:
        config_path: Path to configuration directory or file
        mode: Configuration mode ('main' or 'debug')

    Returns:
        BlueplaneConfig instance
    """
    # Check for config mode override
    mode = os.getenv('BP_CONFIG_MODE', mode)
    return BlueplaneConfig.load(config_path, mode)
