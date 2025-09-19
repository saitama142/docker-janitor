#!/bin/bash

# docker-janitor installer

# --- Configuration ---
INSTALL_DIR="/opt/docker-janitor"
VENV_DIR="$INSTALL_DIR/venv"
SRC_DIR="$INSTALL_DIR/src"
CONFIG_DIR="/etc/docker-janitor"
CONFIG_FILE="$CONFIG_DIR/config.json"
SYSTEMD_DIR="/etc/systemd/system"
SERVICE_FILE_NAME="docker-janitor.service"
SERVICE_FILE_PATH="$SYSTEMD_DIR/$SERVICE_FILE_NAME"
EXECUTABLE_PATH="/usr/local/bin/docker-janitor"

# --- Helper Functions ---
print_info() {
    echo -e "\033[34m[INFO]\033[0m $1"
}

print_success() {
    echo -e "\033[32m[SUCCESS]\033[0m $1"
}

print_error() {
    echo -e "\033[31m[ERROR]\033[0m $1"
    exit 1
}

detect_package_manager() {
    if command -v apt >/dev/null 2>&1; then
        echo "apt"
    elif command -v yum >/dev/null 2>&1; then
        echo "yum"
    elif command -v dnf >/dev/null 2>&1; then
        echo "dnf"
    elif command -v pacman >/dev/null 2>&1; then
        echo "pacman"
    else
        echo "unknown"
    fi
}

install_packages() {
    local pkg_manager=$1
    shift
    local packages="$@"
    
    case $pkg_manager in
        "apt")
            apt update >/dev/null 2>&1
            apt install -y $packages >/dev/null 2>&1
            ;;
        "yum")
            yum install -y $packages >/dev/null 2>&1
            ;;
        "dnf")
            dnf install -y $packages >/dev/null 2>&1
            ;;
        "pacman")
            pacman -Sy --noconfirm $packages >/dev/null 2>&1
            ;;
        *)
            print_error "Unsupported package manager. Please install dependencies manually: $packages"
            ;;
    esac
}

# --- Main Installation Logic ---
main() {
    # 1. Check for root privileges
    if [ "$EUID" -ne 0 ]; then
        print_error "This script must be run with sudo or as root."
    fi

    echo "🐳 Docker Janitor Installer"
    echo "=========================="
    echo "This installer will:"
    echo "• Install system dependencies (Python, Docker, etc.)"
    echo "• Create a dedicated user for the service"
    echo "• Set up the application and systemd service"
    echo "• Configure proper permissions and logging"
    echo ""
    
    read -p "Continue with installation? [Y/n] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Nn]$ ]]; then
        echo "Installation cancelled."
        exit 0
    fi

    print_info "Starting docker-janitor installation..."

    # 2. Detect package manager and install dependencies
    PKG_MANAGER=$(detect_package_manager)
    print_info "Detected package manager: $PKG_MANAGER"
    
    print_info "Installing system dependencies..."
    
    case $PKG_MANAGER in
        "apt")
            PACKAGES="python3 python3-pip python3-venv docker.io"
            ;;
        "yum"|"dnf")
            PACKAGES="python3 python3-pip docker"
            ;;
        "pacman")
            PACKAGES="python python-pip docker"
            ;;
        *)
            print_error "Unsupported package manager: $PKG_MANAGER. Please install python3, python3-pip, python3-venv, and docker manually."
            ;;
    esac
    
    # Install packages
    install_packages $PKG_MANAGER $PACKAGES || print_error "Failed to install required packages."
    
    print_info "System packages installed successfully."

    # 3. Start and enable Docker service
    print_info "Starting Docker service..."
    systemctl start docker >/dev/null 2>&1 || print_info "Docker may already be running."
    systemctl enable docker >/dev/null 2>&1 || print_info "Docker may already be enabled."
    
    # 4. Create docker-janitor user if it doesn't exist
    if ! id "docker-janitor" &>/dev/null; then
        print_info "Creating docker-janitor user..."
        useradd -r -s /bin/false docker-janitor || print_error "Failed to create docker-janitor user."
        usermod -a -G docker docker-janitor || print_error "Failed to add docker-janitor to docker group."
    else
        print_info "docker-janitor user already exists."
        # Ensure user is in docker group
        usermod -a -G docker docker-janitor || print_error "Failed to add docker-janitor to docker group."
    fi

    # 5. Verify Docker is accessible
    sleep 2  # Give Docker a moment to start
    if ! timeout 10 docker info >/dev/null 2>&1; then
        print_info "Docker daemon may still be starting. Installation will continue..."
    fi

    print_info "All dependencies installed and configured."

    # 3. Create docker-janitor user if it doesn't exist
    if ! id "docker-janitor" &>/dev/null; then
        print_info "Creating docker-janitor user..."
        useradd -r -s /bin/false -G docker docker-janitor || print_error "Failed to create docker-janitor user."
    else
        print_info "docker-janitor user already exists."
        # Ensure user is in docker group
        usermod -aG docker docker-janitor || print_error "Failed to add docker-janitor to docker group."
    fi

    # 4. Create directories
    print_info "Creating installation and configuration directories..."
    mkdir -p $INSTALL_DIR || print_error "Failed to create installation directory."
    mkdir -p $SRC_DIR || print_error "Failed to create src directory."
    mkdir -p $CONFIG_DIR || print_error "Failed to create configuration directory."
    mkdir -p /var/lib/docker-janitor || print_error "Failed to create data directory."
    
    # Set ownership for directories that the service user needs access to
    chown -R docker-janitor:docker $CONFIG_DIR 2>/dev/null || print_info "Will set ownership after user creation."
    chown -R docker-janitor:docker /var/lib/docker-janitor 2>/dev/null || print_info "Will set ownership after user creation."

    # 4. Create Python virtual environment
    print_info "Creating Python virtual environment in $VENV_DIR..."
    python3 -m venv $VENV_DIR || print_error "Failed to create virtual environment."

    # 5. Install Python packages
    print_info "Installing Python dependencies..."
    $VENV_DIR/bin/pip3 install --upgrade pip > /dev/null 2>&1
    $VENV_DIR/bin/pip3 install -r requirements.txt || print_error "Failed to install Python packages."

    # 6. Copy source files
    print_info "Copying source files to $SRC_DIR..."
    cp -r src/* $SRC_DIR/ || print_error "Failed to copy source files."
    cp tui.css $SRC_DIR/ || print_error "Failed to copy CSS file."

    # 7. Create default configuration
    if [ ! -f "$CONFIG_FILE" ]; then
        print_info "Creating default configuration file..."
        echo '{
    "daemon_sleep_interval_seconds": 86400,
    "image_age_threshold_days": 30,
    "dry_run_mode": false,
    "excluded_image_patterns": [],
    "log_level": "INFO",
    "log_file": "/var/log/docker-janitor.log",
    "backup_enabled": true,
    "backup_file": "/var/lib/docker-janitor/backup.json"
}' > $CONFIG_FILE || print_error "Failed to create config file."
        chown docker-janitor:docker $CONFIG_FILE 2>/dev/null || print_info "Will set ownership after user creation."
    else
        print_info "Configuration file already exists. Skipping creation."
    fi

    # 8. Install and configure systemd service
    print_info "Installing systemd service..."
    cp $SERVICE_FILE_NAME $SERVICE_FILE_PATH || print_error "Failed to copy systemd service file."
    
    # 9. Create the launcher script
    echo "#!/bin/bash" > "$INSTALL_DIR/launcher.sh"
    echo "# This script activates the venv and runs the main python script." >> "$INSTALL_DIR/launcher.sh"
    echo "source $VENV_DIR/bin/activate" >> "$INSTALL_DIR/launcher.sh"
    echo "python3 $SRC_DIR/main.py \"\$@\"" >> "$INSTALL_DIR/launcher.sh"
    chmod +x "$INSTALL_DIR/launcher.sh"

    # 10. Create executable symlink
    ln -sf "$INSTALL_DIR/launcher.sh" "$EXECUTABLE_PATH" || print_error "Failed to create executable symlink."
    chmod +x "$EXECUTABLE_PATH"

    # 11. Set up log file permissions
    touch /var/log/docker-janitor.log 2>/dev/null || print_info "Could not create log file in /var/log (will use fallback location)"
    if [ -f /var/log/docker-janitor.log ]; then
        chown docker-janitor:docker /var/log/docker-janitor.log 2>/dev/null
        chmod 644 /var/log/docker-janitor.log 2>/dev/null
    fi
    
    # Final ownership fix for all directories
    chown -R docker-janitor:docker $CONFIG_DIR 2>/dev/null || print_info "Ownership will be set on first run."
    chown -R docker-janitor:docker /var/lib/docker-janitor 2>/dev/null || print_info "Ownership will be set on first run."

    systemctl daemon-reload || print_error "Failed to reload systemd daemon."
    
    print_info "Systemd service '$SERVICE_FILE_NAME' installed."

    # 11. Final instructions
    print_success "Installation complete!"
    
    # Final verification
    print_info "Performing final verification..."
    if command -v docker-janitor >/dev/null 2>&1; then
        print_success "docker-janitor command is available."
    else
        print_error "docker-janitor command not found. Installation may have failed."
    fi
    
    echo ""
    print_success "🎉 Docker Janitor has been successfully installed!"
    echo ""
    echo "Available commands:"
    echo "  docker-janitor          # Launch interactive TUI"
    echo "  docker-janitor --dry-run # Preview what would be deleted"
    echo "  docker-janitor --daemon  # Run in daemon mode"
    echo ""
    
    read -p "Do you want to enable and start the background service now? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        print_info "Enabling and starting docker-janitor service..."
        systemctl enable $SERVICE_FILE_NAME >/dev/null 2>&1
        systemctl start $SERVICE_FILE_NAME
        
        # Check service status
        sleep 2
        if systemctl is-active --quiet $SERVICE_FILE_NAME; then
            print_success "docker-janitor service is running successfully!"
        else
            print_error "Service failed to start. Check logs with: sudo journalctl -u docker-janitor -f"
        fi
        
        echo "Check service status with: sudo systemctl status docker-janitor"
    else
        print_info "You can enable the service later by running: sudo systemctl enable --now $SERVICE_FILE_NAME"
    fi
    
    echo ""
    print_info "🚀 You can now run 'docker-janitor' to start the interactive interface!"
    print_info "📚 For help and documentation, see the README.md file."
}

main "$@"
