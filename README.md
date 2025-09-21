# Docker Janitor

A smart, interactive CLI tool to manage and clean up unused Docker images with comprehensive safety features.

## Features

- 🖥️ **Interactive TUI** - Beautiful terminal interface with dashboard, metrics, and progress bars
- 🤖 **Automated Daemon** - Background service for continuous cleanup
- 🔍 **Dry Run Mode** - Preview deletions before executing them
- 🛡️ **Safety Features** - Image exclusion rules and automatic backups
- ⚙️ **Configurable** - Flexible settings for intervals, age thresholds, and patterns
- ⌨️ **Bash Completion** - Auto-complete for `docker-janitor` commands
- 📊 **Real-time Dashboard** - Service status, image count, space usage monitoring
- 🎨 **Modern UI** - Emoji icons, color coding, and responsive design

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
    "image_age_threshold_days": 3,             // Delete images older than 3 days
    "dry_run_mode": false,                     // Set to true for preview-only
    "excluded_image_patterns": ["prod-*", "*important*"],  // Protect images
    "backup_enabled": true                     // Backup image metadata before deletion
}
```

## Interface

The improved TUI includes three main tabs:
- **📊 Dashboard**: Service status, metrics grid with image count/space usage, and recent activity logs
- **⚙️ Settings**: Configure cleanup intervals, exclusion patterns, and test configuration  
- **🧹 Manual Clean**: Scan and selectively delete images with progress tracking and checkboxes

### New Features
- **Progress bars** for scanning operations
- **Metrics dashboard** showing total images and space used
- **Interactive selection** with checkboxes and size calculation
- **Keyboard shortcuts**: `r` (refresh), `s` (scan), `q` (quit)
- **Bash completion**: Type `docker-` and hit `Tab` for auto-completion

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
