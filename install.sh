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

# --- Main Installation Logic ---
main() {
    # 1. Check for root privileges
    if [ "$EUID" -ne 0 ]; then
        print_error "This script must be run with sudo or as root."
    fi

    print_info "Starting docker-janitor installation..."

    # 2. Check for dependencies (python, pip, docker)
    command -v python3 >/dev/null 2>&1 || print_error "Python 3 is not installed. Please install it first."
    command -v pip3 >/dev/null 2>&1 || print_error "pip3 is not installed. Please install it first."
    command -v docker >/dev/null 2>&1 || print_error "Docker is not installed. Please install it first."
    
    if ! docker info >/dev/null 2>&1; then
        print_error "Cannot connect to Docker daemon. Is the Docker daemon running and do you have permissions?"
    fi

    print_info "All dependencies found."

    # 3. Create directories
    print_info "Creating installation and configuration directories..."
    mkdir -p $INSTALL_DIR || print_error "Failed to create installation directory."
    mkdir -p $SRC_DIR || print_error "Failed to create src directory."
    mkdir -p $CONFIG_DIR || print_error "Failed to create configuration directory."

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
    "image_age_threshold_days": 30
}' > $CONFIG_FILE || print_error "Failed to create config file."
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

    systemctl daemon-reload || print_error "Failed to reload systemd daemon."
    
    print_info "Systemd service '$SERVICE_FILE_NAME' installed."

    # 11. Final instructions
    print_success "Installation complete!"
    echo "You can now run the application using the command: docker-janitor"
    
    read -p "Do you want to enable and start the background service now? [y/N] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        systemctl enable $SERVICE_FILE_NAME >/dev/null 2>&1
        systemctl start $SERVICE_FILE_NAME || print_error "Failed to start the service."
        print_success "docker-janitor service has been enabled and started."
    else
        print_info "You can enable the service later by running: sudo systemctl enable --now $SERVICE_FILE_NAME"
    fi
}

main "$@"
