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

is_package_installed() {
    local pkg_manager=$1
    local package=$2
    
    case $pkg_manager in
        "apt")
            dpkg -l | grep -q "^ii  $package " 2>/dev/null
            ;;
        "yum"|"dnf")
            rpm -q $package >/dev/null 2>&1
            ;;
        "pacman")
            pacman -Q $package >/dev/null 2>&1
            ;;
        *)
            return 1
            ;;
    esac
}

install_packages() {
    local pkg_manager=$1
    shift
    local packages="$@"
    
    print_info "Checking and installing packages..."
    
    # Check which packages are already installed
    local to_install=""
    for package in $packages; do
        if is_package_installed $pkg_manager $package; then
            print_info "$package is already installed."
        else
            to_install="$to_install $package"
        fi
    done
    
    # Install only packages that aren't already installed
    if [ -n "$to_install" ]; then
        print_info "Installing packages:$to_install"
        
        case $pkg_manager in
            "apt")
                print_info "Updating package list..."
                if ! apt update; then
                    print_error "Failed to update package list. Check your internet connection and repository configuration."
                fi
                
                print_info "Installing packages with apt..."
                if ! apt install -y $to_install; then
                    print_error "Failed to install packages with apt. Check the error messages above."
                fi
                ;;
            "yum")
                print_info "Installing packages with yum..."
                if ! yum install -y $to_install; then
                    print_error "Failed to install packages with yum. Check the error messages above."
                fi
                ;;
            "dnf")
                print_info "Installing packages with dnf..."
                if ! dnf install -y $to_install; then
                    print_error "Failed to install packages with dnf. Check the error messages above."
                fi
                ;;
            "pacman")
                print_info "Installing packages with pacman..."
                if ! pacman -Sy --noconfirm $to_install; then
                    print_error "Failed to install packages with pacman. Check the error messages above."
                fi
                ;;
            *)
                print_error "Unsupported package manager. Please install dependencies manually: $to_install"
                ;;
        esac
    else
        print_info "All required packages are already installed."
    fi
    
    print_success "Package installation completed."
}

install_docker() {
    print_info "Setting up Docker..."
    
    # Check if docker is already installed and working
    if command -v docker >/dev/null 2>&1 && docker --version >/dev/null 2>&1; then
        print_info "Docker is already installed."
        
        # Check if Docker daemon is accessible
        if docker info >/dev/null 2>&1; then
            print_success "Docker is installed and working correctly."
            return 0
        else
            print_info "Docker is installed but daemon may not be running. Will attempt to start it."
        fi
    else
        print_info "Docker not found. Installing Docker..."
        
        # Try different Docker installation methods
        case $1 in
            "apt")
                # Try docker.io first (simple method)
                if apt install -y docker.io >/dev/null 2>&1; then
                    print_success "Docker installed successfully with docker.io package."
                else
                    print_info "docker.io package failed. Trying Docker CE installation..."
                    
                    # Install Docker CE if docker.io fails
                    apt update >/dev/null 2>&1
                    apt install -y ca-certificates curl gnupg lsb-release >/dev/null 2>&1
                    
                    # Add Docker's official GPG key
                    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg 2>/dev/null
                    
                    # Add Docker repository
                    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list
                    
                    # Install Docker CE
                    apt update >/dev/null 2>&1
                    if apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin; then
                        print_success "Docker CE installed successfully."
                    else
                        print_error "Failed to install Docker. Please install Docker manually and re-run this installer."
                    fi
                fi
                ;;
            "yum"|"dnf")
                $1 install -y docker >/dev/null 2>&1 || print_error "Failed to install Docker with $1."
                ;;
            "pacman")
                pacman -S --noconfirm docker >/dev/null 2>&1 || print_error "Failed to install Docker with pacman."
                ;;
        esac
    fi
    
    # Start and enable Docker service
    print_info "Starting and enabling Docker service..."
    systemctl start docker >/dev/null 2>&1 || print_info "Docker may already be running."
    systemctl enable docker >/dev/null 2>&1 || print_info "Docker may already be enabled."
    
    # Give Docker a moment to start
    sleep 3
    
    # Final verification
    if docker info >/dev/null 2>&1; then
        print_success "Docker is now running and accessible."
    else
        print_info "Docker service started but may need a moment to become ready."
        print_info "You can verify Docker is working later with: sudo docker info"
    fi
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
    
    # Check internet connectivity
    print_info "Checking internet connectivity..."
    if ! ping -c 1 8.8.8.8 >/dev/null 2>&1; then
        print_error "No internet connection detected. Please check your network connection and try again."
    fi
    
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
            PACKAGES="python3 python3-pip python3-venv"
            ;;
        "yum"|"dnf")
            PACKAGES="python3 python3-pip"
            ;;
        "pacman")
            PACKAGES="python python-pip"
            ;;
        *)
            print_error "Unsupported package manager: $PKG_MANAGER. Please install python3, python3-pip, python3-venv manually."
            ;;
    esac
    
    # Install Python packages first
    install_packages $PKG_MANAGER $PACKAGES
    
    # Install Docker separately (handles conflicts better)
    install_docker $PKG_MANAGER
    
    print_info "System packages installed successfully."

    # 3. Create docker-janitor user if it doesn't exist
    if ! id "docker-janitor" &>/dev/null; then
        print_info "Creating docker-janitor user..."
        useradd -r -s /bin/false docker-janitor || print_error "Failed to create docker-janitor user."
        usermod -a -G docker docker-janitor || print_error "Failed to add docker-janitor to docker group."
    else
        print_info "docker-janitor user already exists."
        # Ensure user is in docker group
        usermod -a -G docker docker-janitor || print_error "Failed to add docker-janitor to docker group."
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
    echo "cd $SRC_DIR" >> "$INSTALL_DIR/launcher.sh"
    echo "python3 main.py \"\$@\"" >> "$INSTALL_DIR/launcher.sh"
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
    
    # Add current user to docker group if not already added
    CURRENT_USER=${SUDO_USER:-$USER}
    if [ "$CURRENT_USER" != "root" ] && ! groups "$CURRENT_USER" | grep -q docker; then
        print_info "Adding user '$CURRENT_USER' to docker group..."
        usermod -a -G docker "$CURRENT_USER" || print_info "Failed to add user to docker group. You may need to do this manually."
        print_info "Note: You may need to log out and log back in for docker group changes to take effect."
        print_info "Or run: newgrp docker"
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
    echo ""
    echo "Troubleshooting:"
    echo "• If you get permission errors: sudo docker-janitor"
    echo "• To check service status: sudo systemctl status docker-janitor"
    echo "• To view logs: sudo journalctl -u docker-janitor -f"
    echo "• To restart service: sudo systemctl restart docker-janitor"
}

main "$@"
