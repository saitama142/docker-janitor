# Docker Janitor

A smart, interactive CLI tool to manage and clean up unused Docker images with comprehensive safety features.

## Features

- 🖥️ **Interactive TUI** - Beautiful terminal interface inspired by btop
- 🤖 **Automated Daemon** - Background service for continuous cleanup
- 🔍 **Dry Run Mode** - Preview deletions before executing them
- 🛡️ **Safety Features** - Image exclusion rules and automatic backups
- ⚙️ **Configurable** - Flexible settings for intervals, age thresholds, and patterns

## Quick Start

### Installation
```bash
git clone https://github.com/saitama142/docker-janitor
cd docker-janitor
sudo ./install.sh
```

### Usage
```bash
docker-janitor                    # Launch interactive TUI
docker-janitor --dry-run          # Preview what would be deleted
docker-janitor --daemon           # Run in background mode

# Service management
sudo systemctl start docker-janitor    # Start background service
sudo systemctl status docker-janitor   # Check service status
```

## Configuration

Edit `/etc/docker-janitor/config.json`:

```json
{
    "daemon_sleep_interval_seconds": 86400,    // 24 hours
    "image_age_threshold_days": 30,            // Delete images older than 30 days
    "dry_run_mode": false,                     // Set to true for preview-only
    "excluded_image_patterns": ["prod-*", "*important*"],  // Protect images
    "backup_enabled": true                     // Backup image metadata before deletion
}
```

## Safety Features

- **Image Exclusion**: Protect important images using glob patterns
- **Automatic Backups**: Image metadata saved before deletion
- **Dry Run Mode**: Test configurations safely
- **Age Threshold**: Only delete images older than specified days

## Interface

The TUI includes three main tabs:
- **Dashboard**: Service status and recent activity logs
- **Settings**: Configure cleanup intervals and exclusion patterns  
- **Manual Clean**: Scan and selectively delete images

## Troubleshooting

```bash
# Permission issues
sudo usermod -a -G docker $USER && newgrp docker

# Service issues
sudo journalctl -u docker-janitor -f
sudo systemctl restart docker-janitor

# Test configuration
docker-janitor --dry-run
```

## Requirements

- Python 3.7+
- Docker installed and running
- Linux with systemd

## License

MIT License
