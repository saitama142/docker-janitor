from textual.app import App, ComposeResult, on
from textual.widgets import Header, Footer, Static, TabbedContent, TabPane, Input, Button, DataTable
from textual.containers import Vertical, Horizontal
from textual.binding import Binding
from textual.reactive import reactive
import subprocess
import docker

from . import config
from . import daemon

LOG_FILE = "/var/log/docker-janitor.log"

class DockerJanitorApp(App):
    """The main Textual application for Docker Janitor."""

    TITLE = "Docker Janitor"
    SUB_TITLE = "Your smart Docker image cleaner"
    CSS_PATH = "tui.css"

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
                    Button("Scan for Unused Images", id="scan_button", variant="primary"),
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
        try:
            with open(LOG_FILE, "r") as f:
                lines = f.readlines()
                for line in lines[-10:]: # Show last 10 log entries
                    parts = line.strip().split(" - ")
                    if len(parts) == 3:
                        log_table.add_row(parts[0], parts[1], parts[2])
        except FileNotFoundError:
            log_table.add_row("[bold red]Log file not found at /var/log/docker-janitor.log[/bold red]", "", "")

    def load_settings(self):
        """Loads settings into the input fields."""
        cfg = config.load_config()
        interval_hours = cfg.get("daemon_sleep_interval_seconds", 86400) / 3600
        age_days = cfg.get("image_age_threshold_days", 30)
        self.query_one("#interval_input").value = str(int(interval_hours))
        self.query_one("#age_input").value = str(age_days)

    @on(Button.Pressed)
    def handle_button_press(self, event: Button.Pressed):
        """Handle button press events."""
        if event.button.id == "save_button":
            self.save_settings()
        elif event.button.id == "restart_button":
            self.restart_daemon()
        elif event.button.id == "scan_button":
            self.run_scan()
        elif event.button.id == "delete_button":
            self.delete_images()

    def save_settings(self):
        status = self.query_one("#settings_status")
        try:
            interval_hours = int(self.query_one("#interval_input").value)
            age_days = int(self.query_one("#age_input").value)

            if interval_hours <= 0 or age_days <= 0:
                status.update("[bold red]Values must be positive.[/bold red]")
                return

            config.set_config_value("daemon_sleep_interval_seconds", interval_hours * 3600)
            config.set_config_value("image_age_threshold_days", age_days)
            status.update("[bold green]Settings saved! Restart the daemon to apply them.[/bold green]")
        except ValueError:
            status.update("[bold red]Invalid input. Please use numbers only.[/bold red]")

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
            age_days = config.get_config_value("image_age_threshold_days")
            images_to_scan = daemon.get_unused_images(client, age_days)
            
            for image in images_to_scan:
                tags = ", ".join(image.tags) if image.tags else "[none]"
                size_mb = image.attrs['Size'] / (1024 * 1024)
                created = image.attrs['Created'].split('T')[0]
                image_table.add_row(image.short_id.replace("sha256:", ""), tags, f"{size_mb:.2f}", created, key=image.id)
        except Exception as e:
            self.query_one("#delete_status").update(f"[bold red]Error scanning images: {e}[/bold red]")


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

if __name__ == "__main__":
    app = DockerJanitorApp()
    app.run()