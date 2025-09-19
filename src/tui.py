from textual.app import App, ComposeResult, on
from textual.widgets import Header, Footer, Static, TabbedContent, TabPane, Input, Button, DataTable
from textual.containers import Vertical, Horizontal
from textual.binding import Binding
from textual.reactive import reactive
import subprocess
import docker
import os
import json
from pathlib import Path

from . import config
from . import daemon

LOG_FILE = "/var/log/docker-janitor.log"

def get_log_file():
    """Get the log file path with fallback options."""
    primary_log = "/var/log/docker-janitor.log"
    fallback_log = os.path.expanduser("~/.docker-janitor.log")
    
    if os.path.exists(primary_log):
        return primary_log
    elif os.path.exists(fallback_log):
        return fallback_log
    else:
        return primary_log  # Default, even if it doesn't exist

class DockerJanitorApp(App):
    """The main Textual application for Docker Janitor."""

    TITLE = "Docker Janitor"
    SUB_TITLE = "Your smart Docker image cleaner"
    
    @property
    def CSS_PATH(self):
        """Dynamically resolve CSS path."""
        # Try to find tui.css in the same directory as this file
        current_dir = Path(__file__).parent
        css_file = current_dir / "tui.css"
        if css_file.exists():
            return css_file
        # Fallback to relative path
        return "tui.css"

    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("d", "toggle_dark", "Toggle Dark Mode"),
        Binding("tab", "focus_next", "Switch Pane", show=False),
    ]

    # --- Reactive variables ---
    selected_images = reactive(set)

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        with TabbedContent(id="tabs"):
            with TabPane("Dashboard", id="dashboard_tab"):
                yield Vertical(
                    Static("Docker Janitor Status", classes="header"),
                    Static(id="service_status"),
                    Static(id="next_check"),
                    Static("Recent Activity", classes="header"),
                    DataTable(id="log_table", cursor_type="none"),
                    id="dashboard_content"
                )
            with TabPane("Settings", id="settings_tab"):
                yield Vertical(
                    Static("Configuration", classes="header"),
                    Horizontal(
                        Static("Cleanup Interval (hours):", classes="label"),
                        Input(id="interval_input", type="number"),
                    ),
                    Horizontal(
                        Static("Image Age (days):", classes="label"),
                        Input(id="age_input", type="number"),
                    ),
                    Horizontal(
                        Static("Dry Run Mode:", classes="label"),
                        Input(id="dry_run_input", placeholder="true/false"),
                    ),
                    Horizontal(
                        Static("Exclusion Patterns:", classes="label"),
                        Input(id="exclusions_input", placeholder="pattern1,pattern2"),
                    ),
                    Horizontal(
                        Button("Save Settings", id="save_button", variant="primary"),
                        Button("Restart Daemon", id="restart_button", variant="default"),
                        classes="button_container"
                    ),
                    Static(id="settings_status"),
                    id="settings_content"
                )
            with TabPane("Manual Clean", id="manual_tab"):
                yield Vertical(
                    Static("Manual Image Cleanup", classes="header"),
                    Horizontal(
                        Button("Scan for Unused Images", id="scan_button", variant="primary"),
                        Button("Dry Run Preview", id="dry_run_button", variant="default"),
                        Button("View Backup", id="backup_button", variant="default"),
                    ),
                    DataTable(id="image_table"),
                    Button("Delete Selected Images (0)", id="delete_button", variant="error", disabled=True),
                    Static(id="delete_status"),
                    id="manual_content"
                )
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        self.update_dashboard()
        self.load_settings()
        self.set_interval(5, self.update_dashboard) # Refresh dashboard every 5 seconds

    def update_dashboard(self):
        """Updates the dashboard with current status and logs."""
        # 1. Update Service Status
        try:
            result = subprocess.run(["systemctl", "is-active", "docker-janitor.service"], capture_output=True, text=True)
            status = result.stdout.strip()
            if status == "active":
                self.query_one("#service_status").update("Service Status: [bold green]RUNNING[/bold green]")
            else:
                self.query_one("#service_status").update(f"Service Status: [bold red]{status.upper()}[/bold red]")
        except FileNotFoundError:
            self.query_one("#service_status").update("Service Status: [bold yellow]UNKNOWN (systemctl not found)[/bold yellow]")

        # 2. Update Next Check Time
        cfg = config.load_config()
        interval = cfg.get("daemon_sleep_interval_seconds", 86400)
        self.query_one("#next_check").update(f"Cleanup Interval: Every {int(interval/3600)} hours")

        # 3. Update Log Table
        log_table = self.query_one("#log_table")
        if not log_table.columns:
            log_table.add_columns("Timestamp", "Level", "Message")
        log_table.clear()
        
        log_file_path = get_log_file()
        try:
            with open(log_file_path, "r") as f:
                lines = f.readlines()
                for line in lines[-10:]: # Show last 10 log entries
                    parts = line.strip().split(" - ")
                    if len(parts) == 3:
                        log_table.add_row(parts[0], parts[1], parts[2])
        except FileNotFoundError:
            log_table.add_row(f"[bold red]Log file not found at {log_file_path}[/bold red]", "", "")

    def load_settings(self):
        """Loads settings into the input fields."""
        cfg = config.load_config()
        interval_hours = cfg.get("daemon_sleep_interval_seconds", 86400) / 3600
        age_days = cfg.get("image_age_threshold_days", 30)
        dry_run = cfg.get("dry_run_mode", False)
        exclusions = cfg.get("excluded_image_patterns", [])
        
        self.query_one("#interval_input").value = str(int(interval_hours))
        self.query_one("#age_input").value = str(age_days)
        self.query_one("#dry_run_input").value = str(dry_run).lower()
        self.query_one("#exclusions_input").value = ",".join(exclusions)

    @on(Button.Pressed)
    def handle_button_press(self, event: Button.Pressed):
        """Handle button press events."""
        if event.button.id == "save_button":
            self.save_settings()
        elif event.button.id == "restart_button":
            self.restart_daemon()
        elif event.button.id == "scan_button":
            self.run_scan()
        elif event.button.id == "dry_run_button":
            self.run_dry_run_preview()
        elif event.button.id == "backup_button":
            self.view_backup()
        elif event.button.id == "delete_button":
            self.delete_images()

    def save_settings(self):
        status = self.query_one("#settings_status")
        try:
            interval_hours = int(self.query_one("#interval_input").value)
            age_days = int(self.query_one("#age_input").value)
            dry_run_text = self.query_one("#dry_run_input").value.lower()
            exclusions_text = self.query_one("#exclusions_input").value

            if interval_hours <= 0 or age_days <= 0:
                status.update("[bold red]Values must be positive.[/bold red]")
                return
            
            # Parse dry run setting
            dry_run = dry_run_text in ['true', 'yes', '1', 'on']
            
            # Parse exclusion patterns
            exclusions = [pattern.strip() for pattern in exclusions_text.split(",") if pattern.strip()]

            config.set_config_value("daemon_sleep_interval_seconds", interval_hours * 3600)
            config.set_config_value("image_age_threshold_days", age_days)
            config.set_config_value("dry_run_mode", dry_run)
            config.set_config_value("excluded_image_patterns", exclusions)
            
            status.update("[bold green]Settings saved! Restart the daemon to apply them.[/bold green]")
        except ValueError:
            status.update("[bold red]Invalid input. Please check your values.[/bold red]")

    def restart_daemon(self):
        status = self.query_one("#settings_status")
        status.update("Attempting to restart daemon...")
        try:
            # Note: This requires the user to have passwordless sudo for systemctl, or to run the TUI with sudo.
            subprocess.run(["sudo", "systemctl", "restart", "docker-janitor.service"], check=True)
            status.update("[bold green]Daemon restarted successfully![/bold green]")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            status.update(f"[bold red]Failed to restart daemon. Run with sudo or check permissions.[/bold red]\nError: {e}")

    def run_scan(self):
        """Scans for unused images and populates the table."""
        self.selected_images.clear()
        image_table = self.query_one("#image_table")
        image_table.clear()
        if not image_table.columns:
            image_table.add_columns("ID", "Tags", "Size (MB)", "Created")
        
        try:
            client = docker.from_env()
            cfg = config.load_config()
            age_days = cfg.get("image_age_threshold_days", 30)
            exclusion_patterns = cfg.get("excluded_image_patterns", [])
            images_to_scan = daemon.get_unused_images(client, age_days, exclusion_patterns)
            
            for image in images_to_scan:
                tags = ", ".join(image.tags) if image.tags else "[none]"
                size_mb = image.attrs['Size'] / (1024 * 1024)
                created = image.attrs['Created'].split('T')[0]
                image_table.add_row(image.short_id.replace("sha256:", ""), tags, f"{size_mb:.2f}", created, key=image.id)
        except Exception as e:
            self.query_one("#delete_status").update(f"[bold red]Error scanning images: {e}[/bold red]")

    def run_dry_run_preview(self):
        """Runs a dry-run preview showing what would be deleted."""
        status = self.query_one("#delete_status")
        status.update("Running dry-run preview...")
        
        try:
            # Temporarily run cleanup in dry-run mode
            daemon.cleanup_images(dry_run=True)
            status.update("[bold green]Dry-run preview completed. Check logs for details.[/bold green]")
        except Exception as e:
            status.update(f"[bold red]Error during dry-run: {e}[/bold red]")


    @on(DataTable.RowSelected)
    def on_image_selected(self, event: DataTable.RowSelected):
        """Toggle selection of an image."""
        image_id = event.row_key.value
        if image_id in self.selected_images:
            self.selected_images.remove(image_id)
        else:
            self.selected_images.add(image_id)
        
        # Update button label
        count = len(self.selected_images)
        delete_button = self.query_one("#delete_button")
        delete_button.disabled = count == 0
        delete_button.label = f"Delete Selected Images ({count})"

    def delete_images(self):
        """Deletes the selected images."""
        status = self.query_one("#delete_status")
        if not self.selected_images:
            status.update("[bold yellow]No images selected.[/bold yellow]")
            return

        status.update(f"Deleting {len(self.selected_images)} images...")
        try:
            client = docker.from_env()
            deleted_count = 0
            for image_id in self.selected_images:
                try:
                    client.images.remove(image_id, force=True)
                    deleted_count += 1
                except docker.errors.APIError as e:
                    status.update(f"[bold red]Error deleting {image_id[:12]}: {e}[/bold red]")
            
            status.update(f"[bold green]Successfully deleted {deleted_count} images.[/bold green]")
            self.selected_images.clear()
            self.run_scan() # Refresh the table
        except docker.errors.DockerException as e:
            status.update(f"[bold red]Docker error: {e}[/bold red]")

    def view_backup(self):
        """Display the last backup information."""
        status = self.query_one("#delete_status")
        cfg = config.load_config()
        backup_file = cfg.get("backup_file", "/var/lib/docker-janitor/backup.json")
        
        try:
            with open(backup_file, 'r') as f:
                backup_data = json.load(f)
            
            timestamp = backup_data.get("timestamp", "Unknown")
            images = backup_data.get("images", [])
            
            if not images:
                status.update("[bold yellow]No backup data found.[/bold yellow]")
                return
            
            total_size = sum(img.get("size", 0) for img in images) / (1024 * 1024)
            status.update(f"[bold green]Last backup: {timestamp} - {len(images)} images ({total_size:.2f} MB)[/bold green]")
            
        except FileNotFoundError:
            status.update("[bold yellow]No backup file found.[/bold yellow]")
        except Exception as e:
            status.update(f"[bold red]Error reading backup: {e}[/bold red]")

if __name__ == "__main__":
    app = DockerJanitorApp()
    app.run()