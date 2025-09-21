from textual.app import App, ComposeResult, on
from textual.widgets import Header, Footer, Static, TabbedContent, TabPane, Input, Button, DataTable, Switch, ProgressBar, Label
from textual.containers import Vertical, Horizontal, Container, ScrollableContainer
from textual.binding import Binding
from textual.reactive import reactive
from textual.coordinate import Coordinate
import subprocess
import docker
import os
import json
from pathlib import Path
from datetime import datetime
import asyncio
import threading

# Try relative imports first, fall back to absolute imports
try:
    from . import config
    from . import daemon
except ImportError:
    import config
    import daemon

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

def format_size(bytes_size):
    """Format bytes to human readable string."""
    if bytes_size is None or bytes_size == 0:
        return "0 B"
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} PB"

def format_age(created_str):
    """Format creation date to relative age."""
    try:
        # Parse the ISO date from Docker API
        if 'T' in created_str:
            created_str = created_str.split('T')[0]
        created = datetime.fromisoformat(created_str.replace('Z', '+00:00'))
        age_days = (datetime.now() - created.replace(tzinfo=None)).days
        if age_days == 0:
            return "Today"
        elif age_days == 1:
            return "1 day ago"
        elif age_days < 7:
            return f"{age_days} days ago"
        elif age_days < 30:
            weeks = age_days // 7
            return f"{weeks} week{'s' if weeks > 1 else ''} ago"
        else:
            months = age_days // 30
            return f"{months} month{'s' if months > 1 else ''} ago"
    except:
        return created_str

class DockerJanitorApp(App):
    """The main Textual application for Docker Janitor."""

    TITLE = "🐳 Docker Janitor"
    SUB_TITLE = "Your smart Docker image cleaner"
    
    CSS = """
    Screen {
        background: $surface;
    }
    
    Header {
        background: $primary;
        color: $text;
        text-style: bold;
    }
    
    Footer {
        background: $primary-darken-2;
        color: $text;
    }
    
    TabbedContent {
        height: 100%;
    }
    
    TabPane {
        padding: 1;
    }
    
    .panel {
        background: $surface-lighten-1;
        border: round $primary;
        padding: 1;
        margin: 1;
    }
    
    .metric-box {
        background: $primary-darken-1;
        color: $text;
        text-align: center;
        text-style: bold;
        padding: 1;
        border: round $secondary;
        margin: 0 1;
        height: 3;
    }
    
    .status-good {
        background: $success;
        color: $text;
    }
    
    .status-bad {
        background: $error;
        color: $text;
    }
    
    .status-warning {
        background: $warning;
        color: $text;
    }
    
    Button {
        margin: 0 1 1 0;
        text-style: bold;
    }
    
    DataTable {
        border: round $primary;
        margin: 1 0;
    }
    
    DataTable .datatable--header {
        background: $primary-darken-1;
        text-style: bold;
    }
    
    DataTable .datatable--cursor {
        background: $secondary;
    }
    
    ProgressBar {
        margin: 1 0;
        border: round $primary;
    }
    
    Input {
        border: round $primary;
        margin: 0 1 1 0;
    }
    
    #metrics-row {
        height: 5;
        margin: 1 0;
    }
    
    #button-row {
        height: auto;
        margin: 1 0;
    }
    
    .form-row {
        height: auto;
        margin: 1 0;
    }
    
    .form-label {
        width: 25%;
        text-align: right;
        text-style: bold;
        content-align: center middle;
    }
    
    .form-input {
        width: 75%;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("d", "toggle_dark", "Toggle Dark Mode"),
        Binding("r", "refresh", "Refresh"),
        Binding("s", "scan", "Scan Images"),
        Binding("ctrl+c", "quit", "Quit", priority=True),
    ]

    # --- Reactive variables ---
    selected_images = reactive(set)
    scanning = reactive(False)

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        with TabbedContent():
            with TabPane("📊 Dashboard", id="dashboard"):
                yield ScrollableContainer(
                    Static("🔧 Service Status & Metrics", classes="panel"),
                    Horizontal(
                        Static("Service Status\n[bold green]●[/bold green] Loading...", classes="metric-box", id="service-status"),
                        Static("Total Images\n[bold blue]?[/bold blue]", classes="metric-box", id="total-images"),
                        Static("Space Used\n[bold blue]?[/bold blue]", classes="metric-box", id="space-used"),
                        Static("Next Cleanup\n[bold blue]?[/bold blue]", classes="metric-box", id="next-cleanup"),
                        id="metrics-row"
                    ),
                    Static("📋 Recent Activity", classes="panel"),
                    DataTable(id="log-table", zebra_stripes=True),
                    Button("🔄 Refresh Dashboard", id="refresh-dashboard", variant="success"),
                    id="dashboard-content"
                )
            
            with TabPane("⚙️ Settings", id="settings"):
                yield ScrollableContainer(
                    Static("🛠️ Configuration", classes="panel"),
                    Horizontal(
                        Static("Cleanup Interval (hours):", classes="form-label"),
                        Input(id="interval-input", type="number", placeholder="24", classes="form-input"),
                        classes="form-row"
                    ),
                    Horizontal(
                        Static("Image Age Threshold (days):", classes="form-label"),
                        Input(id="age-input", type="number", placeholder="3", classes="form-input"),
                        classes="form-row"
                    ),
                    Horizontal(
                        Static("Dry Run Mode:", classes="form-label"),
                        Switch(id="dry-run-switch", classes="form-input"),
                        classes="form-row"
                    ),
                    Horizontal(
                        Static("Exclusion Patterns:", classes="form-label"),
                        Input(id="exclusions-input", placeholder="pattern1,pattern2", classes="form-input"),
                        classes="form-row"
                    ),
                    Horizontal(
                        Button("💾 Save Settings", id="save-settings", variant="primary"),
                        Button("🔄 Restart Service", id="restart-service", variant="warning"),
                        Button("🧪 Test Config", id="test-config", variant="default"),
                        id="button-row"
                    ),
                    Static("Ready to configure...", id="settings-status", classes="panel"),
                    id="settings-content"
                )
            
            with TabPane("🧹 Manual Clean", id="manual"):
                yield ScrollableContainer(
                    Static("🔍 Image Cleanup Tools", classes="panel"),
                    Horizontal(
                        Button("🔍 Scan for Unused Images", id="scan-images", variant="primary"),
                        Button("👁️ Dry Run Preview", id="dry-run-preview", variant="default"),
                        Button("📜 View Backup", id="view-backup", variant="default"),
                        Button("🗑️ Delete ALL Unused", id="delete-all", variant="error"),
                        id="button-row"
                    ),
                    ProgressBar(id="scan-progress", show_eta=False),
                    Static("Ready to scan...", id="scan-status", classes="panel"),
                    DataTable(id="image-table", cursor_type="row", zebra_stripes=True),
                    Horizontal(
                        Button("🗑️ Delete Selected (0)", id="delete-selected", variant="error", disabled=True),
                        Static("No images selected", id="selection-info"),
                        classes="form-row"
                    ),
                    Static("", id="delete-status", classes="panel"),
                    id="manual-content"
                )
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        self.update_dashboard()
        self.load_settings()
        self.set_interval(10, self.update_dashboard)
        
        # Hide progress bar initially
        progress = self.query_one("#scan-progress")
        progress.display = False

    def action_refresh(self) -> None:
        """Refresh current view."""
        self.update_dashboard()

    def action_scan(self) -> None:
        """Trigger image scan."""
        current_tab = self.query_one(TabbedContent).active_pane
        if current_tab and current_tab.id == "manual":
            self.run_scan()

    def update_dashboard(self):
        """Updates the dashboard with current status and logs."""
        try:
            # 1. Update Service Status
            try:
                result = subprocess.run(["systemctl", "is-active", "docker-janitor.service"], 
                                      capture_output=True, text=True, timeout=5)
                status = result.stdout.strip()
                if status == "active":
                    self.query_one("#service-status").update("Service Status\n[bold green]● RUNNING[/bold green]")
                elif status == "inactive":
                    self.query_one("#service-status").update("Service Status\n[bold yellow]⏸ STOPPED[/bold yellow]")
                else:
                    self.query_one("#service-status").update(f"Service Status\n[bold red]✗ {status.upper()}[/bold red]")
            except (FileNotFoundError, subprocess.TimeoutExpired):
                self.query_one("#service-status").update("Service Status\n[bold yellow]? UNKNOWN[/bold yellow]")

            # 2. Update Docker Stats
            try:
                client = docker.from_env()
                images = client.images.list(all=True)
                total_size = sum(img.attrs.get('Size', 0) for img in images)
                
                self.query_one("#total-images").update(f"Total Images\n[bold blue]{len(images)}[/bold blue]")
                self.query_one("#space-used").update(f"Space Used\n[bold blue]{format_size(total_size)}[/bold blue]")
            except Exception:
                self.query_one("#total-images").update("Total Images\n[bold red]Error[/bold red]")
                self.query_one("#space-used").update("Space Used\n[bold red]Error[/bold red]")

            # 3. Update Next Check Time
            cfg = config.load_config()
            interval = cfg.get("daemon_sleep_interval_seconds", 86400)
            hours = int(interval/3600)
            self.query_one("#next-cleanup").update(f"Next Cleanup\n[bold blue]{hours}h[/bold blue]")

            # 4. Update Log Table
            log_table = self.query_one("#log-table")
            if not log_table.columns:
                log_table.add_columns("🕐 Time", "📊 Level", "💬 Message")
            log_table.clear()
            
            log_file_path = get_log_file()
            try:
                with open(log_file_path, "r") as f:
                    lines = f.readlines()
                    for line in lines[-15:]:
                        if " - " in line:
                            parts = line.strip().split(" - ", 2)
                            if len(parts) >= 3:
                                timestamp = parts[0].split()[-1] if parts[0] else ""
                                level = parts[1]
                                message = parts[2][:60] + "..." if len(parts[2]) > 60 else parts[2]
                                
                                # Color code levels
                                if "ERROR" in level:
                                    level = f"[red]{level}[/red]"
                                elif "WARNING" in level:
                                    level = f"[yellow]{level}[/yellow]"
                                elif "INFO" in level:
                                    level = f"[green]{level}[/green]"
                                
                                log_table.add_row(timestamp, level, message)
            except FileNotFoundError:
                log_table.add_row("", "[red]ERROR[/red]", f"Log file not found: {log_file_path}")
        except Exception as e:
            # Fallback if anything fails
            pass

    def load_settings(self):
        """Loads settings into the input fields."""
        try:
            cfg = config.load_config()
            interval_hours = cfg.get("daemon_sleep_interval_seconds", 86400) / 3600
            age_days = cfg.get("image_age_threshold_days", 3)
            dry_run = cfg.get("dry_run_mode", False)
            exclusions = cfg.get("excluded_image_patterns", [])
            
            self.query_one("#interval-input").value = str(int(interval_hours))
            self.query_one("#age-input").value = str(age_days)
            self.query_one("#dry-run-switch").value = dry_run
            self.query_one("#exclusions-input").value = ",".join(exclusions)
        except Exception:
            pass

    @on(Button.Pressed)
    def handle_button_press(self, event: Button.Pressed):
        """Handle button press events."""
        button_id = event.button.id
        
        if button_id == "save-settings":
            self.save_settings()
        elif button_id == "restart-service":
            self.restart_service()
        elif button_id == "test-config":
            self.test_config()
        elif button_id == "scan-images":
            self.run_scan()
        elif button_id == "dry-run-preview":
            self.run_dry_run_preview()
        elif button_id == "view-backup":
            self.view_backup()
        elif button_id == "delete-selected":
            self.delete_selected_images()
        elif button_id == "delete-all":
            self.delete_all_unused()
        elif button_id == "refresh-dashboard":
            self.update_dashboard()

    def save_settings(self):
        """Save configuration settings."""
        status = self.query_one("#settings-status")
        try:
            interval_hours = int(self.query_one("#interval-input").value or "24")
            age_days = int(self.query_one("#age-input").value or "3")
            dry_run = self.query_one("#dry-run-switch").value
            exclusions_text = self.query_one("#exclusions-input").value

            if interval_hours <= 0 or age_days < 0:
                status.update("[bold red]❌ Values must be positive.[/bold red]")
                return
            
            exclusions = [pattern.strip() for pattern in exclusions_text.split(",") if pattern.strip()]

            config.set_config_value("daemon_sleep_interval_seconds", interval_hours * 3600)
            config.set_config_value("image_age_threshold_days", age_days)
            config.set_config_value("dry_run_mode", dry_run)
            config.set_config_value("excluded_image_patterns", exclusions)
            
            status.update("[bold green]✅ Settings saved! Restart service to apply.[/bold green]")
        except ValueError:
            status.update("[bold red]❌ Invalid input. Please check values.[/bold red]")

    def test_config(self):
        """Test the configuration."""
        status = self.query_one("#settings-status")
        try:
            interval_hours = int(self.query_one("#interval-input").value or "24")
            age_days = int(self.query_one("#age-input").value or "3")
            
            if interval_hours <= 0 or age_days < 0:
                status.update("[bold red]❌ Invalid values.[/bold red]")
                return
                
            client = docker.from_env()
            client.ping()
            
            status.update("[bold green]✅ Configuration valid![/bold green]")
        except docker.errors.DockerException:
            status.update("[bold red]❌ Cannot connect to Docker.[/bold red]")
        except ValueError:
            status.update("[bold red]❌ Invalid input values.[/bold red]")
        except Exception as e:
            status.update(f"[bold red]❌ Error: {str(e)[:30]}[/bold red]")

    def restart_service(self):
        """Restart the Docker Janitor service."""
        status = self.query_one("#settings-status")
        status.update("🔄 Restarting service...")
        try:
            subprocess.run(["sudo", "systemctl", "restart", "docker-janitor.service"], 
                          check=True, timeout=10)
            status.update("[bold green]✅ Service restarted![/bold green]")
            self.update_dashboard()
        except subprocess.TimeoutExpired:
            status.update("[bold red]❌ Restart timed out.[/bold red]")
        except (subprocess.CalledProcessError, FileNotFoundError):
            status.update("[bold red]❌ Failed to restart service.[/bold red]")

    def run_scan(self):
        """Scan for unused images."""
        if self.scanning:
            return
            
        self.scanning = True
        self.selected_images.clear()
        
        # Show progress and update UI
        progress = self.query_one("#scan-progress")
        progress.display = True
        progress.update(total=100, progress=10)
        
        scan_status = self.query_one("#scan-status")
        scan_status.update("🔍 Scanning for unused images...")
        
        image_table = self.query_one("#image-table")
        image_table.clear()
        if not image_table.columns:
            image_table.add_columns("Select", "🆔 Image ID", "🏷️ Tags", "💾 Size", "📅 Age")
        
        try:
            client = docker.from_env()
            cfg = config.load_config()
            age_days = cfg.get("image_age_threshold_days", 3)
            exclusion_patterns = cfg.get("excluded_image_patterns", [])
            
            progress.update(progress=30)
            images_to_scan = daemon.get_unused_images(client, age_days, exclusion_patterns)
            progress.update(progress=70)
            
            total_size = 0
            for image in images_to_scan:
                tags = ", ".join(image.tags) if image.tags else "[dangling]"
                if len(tags) > 40:
                    tags = tags[:37] + "..."
                    
                size_bytes = image.attrs.get('Size', 0)
                size_str = format_size(size_bytes)
                total_size += size_bytes
                
                created = image.attrs.get('Created', '')
                age_str = format_age(created)
                
                image_table.add_row(
                    "☐",
                    image.short_id.replace("sha256:", "")[:12],
                    tags,
                    size_str,
                    age_str,
                    key=image.id
                )
            
            progress.update(progress=100)
            progress.display = False
            
            if len(images_to_scan) == 0:
                scan_status.update("✅ No unused images found!")
            else:
                scan_status.update(f"✅ Found {len(images_to_scan)} unused images ({format_size(total_size)} total)")
            
            self.update_selection_info()
            
        except Exception as e:
            scan_status.update(f"[bold red]❌ Error: {str(e)[:40]}[/bold red]")
            progress.display = False
        finally:
            self.scanning = False

    def update_selection_info(self):
        """Update selection information."""
        selection_info = self.query_one("#selection-info")
        count = len(self.selected_images)
        
        if count == 0:
            selection_info.update("No images selected")
        else:
            try:
                client = docker.from_env()
                total_size = 0
                for image_id in self.selected_images:
                    try:
                        img = client.images.get(image_id)
                        total_size += img.attrs.get('Size', 0)
                    except:
                        pass
                selection_info.update(f"{count} selected ({format_size(total_size)})")
            except:
                selection_info.update(f"{count} selected")

    def run_dry_run_preview(self):
        """Run a dry-run preview."""
        status = self.query_one("#delete-status")
        status.update("🧪 Running dry-run preview...")
        
        try:
            daemon.cleanup_images(dry_run=True)
            status.update("[bold green]✅ Dry-run completed. Check logs.[/bold green]")
            self.update_dashboard()
        except Exception as e:
            status.update(f"[bold red]❌ Error: {str(e)[:40]}[/bold red]")

    @on(DataTable.RowSelected)
    def on_image_selected(self, event: DataTable.RowSelected):
        """Toggle selection of an image."""
        if event.data_table.id != "image-table":
            return
            
        image_id = event.row_key.value
        row_index = event.cursor_row
        
        if image_id in self.selected_images:
            self.selected_images.remove(image_id)
            event.data_table.update_cell_at(Coordinate(row_index, 0), "☐")
        else:
            self.selected_images.add(image_id)
            event.data_table.update_cell_at(Coordinate(row_index, 0), "☑️")
        
        count = len(self.selected_images)
        delete_button = self.query_one("#delete-selected")
        delete_button.disabled = count == 0
        delete_button.label = f"🗑️ Delete Selected ({count})"
        
        self.update_selection_info()

    def delete_selected_images(self):
        """Delete selected images."""
        status = self.query_one("#delete-status")
        if not self.selected_images:
            status.update("[bold yellow]⚠️ No images selected.[/bold yellow]")
            return

        count = len(self.selected_images)
        status.update(f"🗑️ Deleting {count} images...")
        
        try:
            client = docker.from_env()
            deleted_count = 0
            deleted_size = 0
            
            for image_id in list(self.selected_images):
                try:
                    img = client.images.get(image_id)
                    size = img.attrs.get('Size', 0)
                    client.images.remove(image_id, force=True)
                    deleted_count += 1
                    deleted_size += size
                except docker.errors.APIError as e:
                    status.update(f"[bold red]❌ Error deleting image[/bold red]")
                    break
            
            if deleted_count > 0:
                status.update(f"[bold green]✅ Deleted {deleted_count} images ({format_size(deleted_size)})[/bold green]")
                self.selected_images.clear()
                self.run_scan()
                self.update_dashboard()
            
        except docker.errors.DockerException as e:
            status.update(f"[bold red]❌ Docker error[/bold red]")

    def delete_all_unused(self):
        """Delete all unused images."""
        status = self.query_one("#delete-status")
        status.update("🗑️ Deleting ALL unused images...")
        
        try:
            daemon.cleanup_images(dry_run=False)
            status.update("[bold green]✅ Cleanup completed![/bold green]")
            self.run_scan()
            self.update_dashboard()
        except Exception as e:
            status.update(f"[bold red]❌ Error: {str(e)[:40]}[/bold red]")

    def view_backup(self):
        """View backup information."""
        status = self.query_one("#delete-status")
        cfg = config.load_config()
        backup_file = cfg.get("backup_file", "/var/lib/docker-janitor/backup.json")
        
        try:
            with open(backup_file, 'r') as f:
                backup_data = json.load(f)
            
            timestamp = backup_data.get("timestamp", "Unknown")
            images = backup_data.get("images", [])
            
            if not images:
                status.update("[bold yellow]📋 No backup data found.[/bold yellow]")
                return
            
            total_size = sum(img.get("size", 0) for img in images)
            try:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                time_str = dt.strftime("%Y-%m-%d %H:%M")
            except:
                time_str = timestamp
                
            status.update(f"[bold green]📋 Last backup: {time_str} - {len(images)} images ({format_size(total_size)})[/bold green]")
            
        except FileNotFoundError:
            status.update("[bold yellow]📋 No backup file found.[/bold yellow]")
        except Exception as e:
            status.update(f"[bold red]❌ Error reading backup[/bold red]")

if __name__ == "__main__":
    app = DockerJanitorApp()
    app.run()