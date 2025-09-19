# Docker Janitor

A smart, interactive CLI tool to manage and clean up unused Docker images with comprehensive safety features.

## Features

- 🖥️ **Interactive TUI** - Beautiful terminal interface inspired by btop
- 🤖 **Automated Daemon** - Background service for continuous cleanup
- 🔍 **Dry Run Mode** - Preview deletions before executing them
- 🛡️ **Safety Features** - Image exclusion rules and automatic backups
- ⚙️ **Configurable** - Flexible settings for intervals, age thresholds, and patterns
- 📊 **Comprehensive Logging** - Detailed logs with rotation and configurable levels
- 🔐 **Security Focused** - Runs as non-root user with docker group permissions

## Installation

To install docker-janitor, run the following command:

```bash
sudo ./install.sh
```

The installer will:
- Create a dedicated `docker-janitor` user
- Set up a Python virtual environment
- Install all dependencies
- Configure systemd service
- Set up proper permissions and directories

## Usage

### Interactive Mode (Default)
Launch the beautiful TUI interface:
```bash
docker-janitor
```

### Command Line Options
```bash
docker-janitor --dry-run    # Preview what would be deleted
docker-janitor --daemon     # Run in background daemon mode
```

### Service Management
```bash
sudo systemctl start docker-janitor    # Start the service
sudo systemctl stop docker-janitor     # Stop the service
sudo systemctl status docker-janitor   # Check service status
sudo systemctl enable docker-janitor   # Enable auto-start
```

## Configuration

Configuration is stored in `/etc/docker-janitor/config.json`:

```json
{
    "daemon_sleep_interval_seconds": 86400,
    "image_age_threshold_days": 30,
    "dry_run_mode": false,
    "excluded_image_patterns": ["important-*", "prod-*"],
    "log_level": "INFO",
    "log_file": "/var/log/docker-janitor.log",
    "backup_enabled": true,
    "backup_file": "/var/lib/docker-janitor/backup.json"
}
```

### Configuration Options

- **daemon_sleep_interval_seconds**: How often the daemon runs (default: 24 hours)
- **image_age_threshold_days**: Minimum age of images to consider for deletion (default: 30 days)
- **dry_run_mode**: If true, only preview deletions without actually removing images
- **excluded_image_patterns**: List of glob patterns to exclude from deletion
- **log_level**: Logging level (DEBUG, INFO, WARNING, ERROR)
- **log_file**: Primary log file location (falls back to ~/.docker-janitor.log)
- **backup_enabled**: Whether to backup image metadata before deletion
- **backup_file**: Location to store backup information

## Safety Features

### Image Exclusion
Protect important images using glob patterns:
```json
"excluded_image_patterns": [
    "prod-*",           # Exclude production images
    "*important*",      # Exclude anything with "important"
    "nginx:latest",     # Exclude specific tag
    "sha256:abc123*"    # Exclude by image ID
]
```

### Automatic Backups
Before deletion, image metadata is automatically backed up, including:
- Image ID and tags
- Creation timestamp
- Size and labels
- Deletion timestamp

### Dry Run Mode
Always test your configuration:
```bash
docker-janitor --dry-run
```

## TUI Interface

The interactive interface includes three main tabs:

### Dashboard
- Service status monitoring
- Cleanup interval display
- Recent activity logs
- Real-time updates

### Settings
- Configure cleanup intervals
- Set image age thresholds
- Enable/disable dry run mode
- Manage exclusion patterns
- Save and restart daemon

### Manual Clean
- Scan for unused images
- Preview deletions (dry run)
- Select specific images for deletion
- View backup information

## Logging

Logs are written to `/var/log/docker-janitor.log` with automatic rotation:
- Maximum file size: 10MB
- Backup count: 5 files
- Fallback location: `~/.docker-janitor.log`

### Log Levels
- **INFO**: Normal operations and image deletions
- **WARNING**: Non-critical issues
- **ERROR**: Failures and connection issues
- **DEBUG**: Detailed troubleshooting information

## Security

- Runs as dedicated `docker-janitor` user (not root)
- Member of `docker` group for Docker access
- Proper file permissions and ownership
- Comprehensive input validation
- Safe fallback mechanisms

## Troubleshooting

### Permission Issues
```bash
# Check if docker-janitor user exists
id docker-janitor

# Verify docker group membership
groups docker-janitor

# Check service logs
sudo journalctl -u docker-janitor -f
```

### Configuration Issues
```bash
# Validate configuration
python3 -c "import json; print(json.load(open('/etc/docker-janitor/config.json')))"

# Reset to defaults
sudo rm /etc/docker-janitor/config.json
sudo systemctl restart docker-janitor
```

### Docker Connection Issues
```bash
# Test Docker access as docker-janitor user
sudo -u docker-janitor docker ps

# Check Docker daemon status
sudo systemctl status docker
```

## Requirements

- Python 3.7+
- Docker installed and running
- systemd (for service management)
- Root access for installation

## License

This project is open source and available under the MIT License.
