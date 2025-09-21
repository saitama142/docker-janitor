from textual.app import App, ComposeResult, on
from textual.widgets import Header, Footer, Static, TabbedContent, TabPane, Input, Button, DataTable, Switch, ProgressBar, Label
from textual.containers import Vertical, Horizontal, Grid, Container
from textual.binding import Binding
from textual.reactive import reactive
from textual.coordinate import Coordinate
from textual.message import Message
import subprocess
import docker
import os
import json
from pathlib import Path
from datetime import datetime
import asyncio

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

class ScanProgressMessage(Message):
    """Message sent when scan progress updates."""
    def __init__(self, current: int, total: int, status: str) -> None:
        self.current = current
        self.total = total
        self.status = status
        super().__init__()

class DockerJanitorApp(App):
    """The main Textual application for Docker Janitor."""

    TITLE = "🐳 Docker Janitor"
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
        with TabbedContent(id="tabs"):
            with TabPane("📊 Dashboard", id="dashboard_tab"):
                yield Container(
                    Grid(
                        Static("🔧 Service Status", classes="metric-title"),
                        Static(id="service_status", classes="metric-value"),
                        Static("⏰ Next Cleanup", classes="metric-title"), 
                        Static(id="next_check", classes="metric-value"),
                        Static("📦 Total Images", classes="metric-title"),
                        Static(id="total_images", classes="metric-value"),
                        Static("💾 Space Used", classes="metric-title"),
                        Static(id="space_used", classes="metric-value"),
                        id="metrics_grid"
                    ),
                    Static("📋 Recent Activity", classes="section-header"),
                    DataTable(id="log_table", cursor_type="none", zebra_stripes=True),
                    Button("🔄 Refresh Dashboard", id="refresh_dashboard", variant="success"),
                    id="dashboard_content"
                )
            with TabPane("⚙️ Settings", id="settings_tab"):
                yield Container(
                    Static("🛠️ Configuration", classes="section-header"),
                    Grid(
                        Label("Cleanup Interval (hours):"),
                        Input(id="interval_input", type="number", placeholder="24"),
                        Label("Image Age Threshold (days):"),
                        Input(id="age_input", type="number", placeholder="7"),
                        Label("Dry Run Mode:"),
                        Switch(id="dry_run_switch"),
                        Label("Exclusion Patterns:"),
                        Input(id="exclusions_input", placeholder="pattern1,pattern2"),
                        id="settings_grid"
                    ),
                    Horizontal(
                        Button("💾 Save Settings", id="save_button", variant="primary"),
                        Button("🔄 Restart Service", id="restart_button", variant="warning"),
                        Button("🧪 Test Config", id="test_button", variant="default"),
                        classes="button_row"
                    ),
                    Static(id="settings_status", classes="status-message"),
                    id="settings_content"
                )
            with TabPane("🧹 Manual Clean", id="manual_tab"):
                yield Container(
                    Static("🔍 Image Cleanup", classes="section-header"),
                    Horizontal(
                        Button("🔍 Scan for Unused Images", id="scan_button", variant="primary"),
                        Button("👁️ Dry Run Preview", id="dry_run_button", variant="default"),
                        Button("📜 View Backup", id="backup_button", variant="default"),
                        Button("🗑️ Delete ALL Unused", id="delete_all_button", variant="error"),
                        classes="button_row"
                    ),
                    ProgressBar(id="scan_progress", show_eta=False),
                    Static(id="scan_status", classes="status-message"),
                    DataTable(id="image_table", cursor_type="row", zebra_stripes=True),
                    Horizontal(
                        Button("🗑️ Delete Selected (0)", id="delete_button", variant="error", disabled=True),
                        Static(id="selection_info", classes="selection-info"),
                        classes="bottom_row"
                    ),
                    Static(id="delete_status", classes="status-message"),
                    id="manual_content"
                )
        yield Footer()

    def on_mount(self) -> None:
        """Called when the app is mounted."""
        self.update_dashboard()
        self.load_settings()
        self.set_interval(10, self.update_dashboard)  # Refresh dashboard every 10 seconds
        
        # Hide progress bar initially
        self.query_one("#scan_progress").display = False

    def action_refresh(self) -> None:
        """Refresh current view."""
        self.update_dashboard()

    def action_scan(self) -> None:
        """Trigger image scan."""
        current_tab = self.query_one(TabbedContent).active_pane
        if current_tab and current_tab.id == "manual_tab":
            self.run_scan_sync()

    def run_scan_sync(self):
        """Start the async scan process."""
        self.run_worker(self.run_scan(), exclusive=True)

    def update_dashboard(self):
        """Updates the dashboard with current status and logs."""
        # 1. Update Service Status
        try:
            result = subprocess.run(["systemctl", "is-active", "docker-janitor.service"], 
                                  capture_output=True, text=True, timeout=5)
            status = result.stdout.strip()
            if status == "active":
                self.query_one("#service_status").update("[bold green]✅ RUNNING[/bold green]")
            elif status == "inactive":
                self.query_one("#service_status").update("[bold yellow]⏸️ STOPPED[/bold yellow]")
            else:
                self.query_one("#service_status").update(f"[bold red]❌ {status.upper()}[/bold red]")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self.query_one("#service_status").update("[bold yellow]❓ UNKNOWN[/bold yellow]")

        # 2. Update Docker Stats
        try:
            client = docker.from_env()
            images = client.images.list(all=True)
            total_size = sum(img.attrs.get('Size', 0) for img in images)
            
            self.query_one("#total_images").update(f"[bold blue]{len(images)}[/bold blue]")
            self.query_one("#space_used").update(f"[bold blue]{format_size(total_size)}[/bold blue]")
        except Exception:
            self.query_one("#total_images").update("[bold red]Error[/bold red]")
            self.query_one("#space_used").update("[bold red]Error[/bold red]")

        # 3. Update Next Check Time
        cfg = config.load_config()
        interval = cfg.get("daemon_sleep_interval_seconds", 86400)
        hours = int(interval/3600)
        self.query_one("#next_check").update(f"[bold blue]{hours}h[/bold blue]")

        # 4. Update Log Table
        log_table = self.query_one("#log_table")
        if not log_table.columns:
            log_table.add_columns("🕐 Time", "📊 Level", "💬 Message")
        log_table.clear()
        
        log_file_path = get_log_file()
        try:
            with open(log_file_path, "r") as f:
                lines = f.readlines()
                for line in lines[-15:]:  # Show last 15 log entries
                    if " - " in line:
                        parts = line.strip().split(" - ", 2)
                        if len(parts) >= 3:
                            timestamp = parts[0].split()[-1] if parts[0] else ""  # Get time part
                            level = parts[1]
                            message = parts[2][:80] + "..." if len(parts[2]) > 80 else parts[2]
                            
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

    def load_settings(self):
        """Loads settings into the input fields."""
        cfg = config.load_config()
        interval_hours = cfg.get("daemon_sleep_interval_seconds", 86400) / 3600
        age_days = cfg.get("image_age_threshold_days", 7)
        dry_run = cfg.get("dry_run_mode", False)
        exclusions = cfg.get("excluded_image_patterns", [])
        
        self.query_one("#interval_input").value = str(int(interval_hours))
        self.query_one("#age_input").value = str(age_days)
        self.query_one("#dry_run_switch").value = dry_run
        self.query_one("#exclusions_input").value = ",".join(exclusions)

    @on(Button.Pressed)
    def handle_button_press(self, event: Button.Pressed):
        """Handle button press events."""
        if event.button.id == "save_button":
            self.save_settings()
        elif event.button.id == "restart_button":
            self.restart_daemon()
        elif event.button.id == "test_button":
            self.test_config()
        elif event.button.id == "scan_button":
            self.run_scan_sync()
        elif event.button.id == "dry_run_button":
            self.run_dry_run_preview()
        elif event.button.id == "backup_button":
            self.view_backup()
        elif event.button.id == "delete_button":
            self.delete_selected_images()
        elif event.button.id == "delete_all_button":
            self.delete_all_unused()
        elif event.button.id == "refresh_dashboard":
            self.update_dashboard()

    def save_settings(self):
        status = self.query_one("#settings_status")
        try:
            interval_hours = int(self.query_one("#interval_input").value or "24")
            age_days = int(self.query_one("#age_input").value or "7")
            dry_run = self.query_one("#dry_run_switch").value
            exclusions_text = self.query_one("#exclusions_input").value

            if interval_hours <= 0 or age_days < 0:
                status.update("[bold red]❌ Values must be positive.[/bold red]")
                return
            
            # Parse exclusion patterns
            exclusions = [pattern.strip() for pattern in exclusions_text.split(",") if pattern.strip()]

            config.set_config_value("daemon_sleep_interval_seconds", interval_hours * 3600)
            config.set_config_value("image_age_threshold_days", age_days)
            config.set_config_value("dry_run_mode", dry_run)
            config.set_config_value("excluded_image_patterns", exclusions)
            
            status.update("[bold green]✅ Settings saved! Restart service to apply changes.[/bold green]")
        except ValueError:
            status.update("[bold red]❌ Invalid input. Please check your values.[/bold red]")

    def test_config(self):
        """Test the configuration without saving."""
        status = self.query_one("#settings_status")
        try:
            interval_hours = int(self.query_one("#interval_input").value or "24")
            age_days = int(self.query_one("#age_input").value or "7")
            
            if interval_hours <= 0 or age_days < 0:
                status.update("[bold red]❌ Invalid values detected.[/bold red]")
                return
                
            # Test Docker connection
            client = docker.from_env()
            client.ping()
            
            status.update("[bold green]✅ Configuration looks good![/bold green]")
        except docker.errors.DockerException:
            status.update("[bold red]❌ Cannot connect to Docker daemon.[/bold red]")
        except ValueError:
            status.update("[bold red]❌ Invalid input values.[/bold red]")
        except Exception as e:
            status.update(f"[bold red]❌ Error: {str(e)[:50]}[/bold red]")

    def restart_daemon(self):
        status = self.query_one("#settings_status")
        status.update("🔄 Restarting service...")
        try:
            subprocess.run(["sudo", "systemctl", "restart", "docker-janitor.service"], 
                          check=True, timeout=10)
            status.update("[bold green]✅ Service restarted successfully![/bold green]")
            self.update_dashboard()
        except subprocess.TimeoutExpired:
            status.update("[bold red]❌ Restart timed out.[/bold red]")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            status.update("[bold red]❌ Failed to restart service. Check permissions.[/bold red]")

    async def run_scan(self):
        """Scans for unused images and populates the table."""
        if self.scanning:
            return
            
        self.scanning = True
        self.selected_images.clear()
        
        # Show progress and update UI
        progress = self.query_one("#scan_progress")
        progress.display = True
        progress.update(total=100, progress=0)
        
        scan_status = self.query_one("#scan_status")
        scan_status.update("🔍 Initializing scan...")
        
        image_table = self.query_one("#image_table")
        image_table.clear()
        if not image_table.columns:
            image_table.add_columns("✓", "🆔 Image ID", "🏷️ Tags", "💾 Size", "📅 Age", "📊 Status")
        
        try:
            client = docker.from_env()
            cfg = config.load_config()
            age_days = cfg.get("image_age_threshold_days", 7)
            exclusion_patterns = cfg.get("excluded_image_patterns", [])
            
            scan_status.update("🔍 Getting image list...")
            progress.update(progress=20)
            
            images_to_scan = daemon.get_unused_images(client, age_days, exclusion_patterns)
            total_images = len(images_to_scan)
            
            if total_images == 0:
                scan_status.update("✅ No unused images found!")
                progress.display = False
                self.scanning = False
                return
            
            scan_status.update(f"📊 Found {total_images} unused images")
            
            total_size = 0
            for i, image in enumerate(images_to_scan):
                tags = ", ".join(image.tags) if image.tags else "[dangling]"
                if len(tags) > 40:
                    tags = tags[:37] + "..."
                    
                size_bytes = image.attrs.get('Size', 0)
                size_str = format_size(size_bytes)
                total_size += size_bytes
                
                created = image.attrs.get('Created', '')
                age_str = format_age(created)
                
                # Determine status based on tags and size
                if not image.tags:
                    status = "[yellow]🔸 Dangling[/yellow]"
                elif size_bytes > 1024**3:  # > 1GB
                    status = "[red]🔴 Large[/red]"
                else:
                    status = "[green]🟢 Safe[/green]"
                
                image_table.add_row(
                    "☐",  # Checkbox placeholder
                    image.short_id.replace("sha256:", "")[:12],
                    tags,
                    size_str,
                    age_str,
                    status,
                    key=image.id
                )
                
                # Update progress
                progress_val = 20 + int((i + 1) / total_images * 80)
                progress.update(progress=progress_val)
                
                # Allow UI to update
                await asyncio.sleep(0.01)
            
            scan_status.update(f"✅ Scan complete: {total_images} unused images ({format_size(total_size)} total)")
            progress.display = False
            
            # Update selection info
            self.update_selection_info()
            
        except Exception as e:
            scan_status.update(f"[bold red]❌ Error during scan: {str(e)[:50]}[/bold red]")
            progress.display = False
        finally:
            self.scanning = False

    def update_selection_info(self):
        """Update the selection information display."""
        selection_info = self.query_one("#selection_info")
        count = len(self.selected_images)
        
        if count == 0:
            selection_info.update("No images selected")
        else:
            # Calculate total size of selected images
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
        """Runs a dry-run preview showing what would be deleted."""
        status = self.query_one("#delete_status")
        status.update("🧪 Running dry-run preview...")
        
        try:
            daemon.cleanup_images(dry_run=True)
            status.update("[bold green]✅ Dry-run preview completed. Check logs for details.[/bold green]")
            self.update_dashboard()  # Refresh logs
        except Exception as e:
            status.update(f"[bold red]❌ Error during dry-run: {str(e)[:50]}[/bold red]")

    @on(DataTable.RowSelected)
    def on_image_selected(self, event: DataTable.RowSelected):
        """Toggle selection of an image."""
        if event.data_table.id != "image_table":
            return
            
        image_id = event.row_key.value
        row_index = event.cursor_row
        
        if image_id in self.selected_images:
            self.selected_images.remove(image_id)
            # Update checkbox to empty
            event.data_table.update_cell_at(Coordinate(row_index, 0), "☐")
        else:
            self.selected_images.add(image_id)
            # Update checkbox to checked
            event.data_table.update_cell_at(Coordinate(row_index, 0), "☑️")
        
        # Update button label and selection info
        count = len(self.selected_images)
        delete_button = self.query_one("#delete_button")
        delete_button.disabled = count == 0
        delete_button.label = f"🗑️ Delete Selected ({count})"
        
        self.update_selection_info()

    def delete_selected_images(self):
        """Deletes the selected images."""
        status = self.query_one("#delete_status")
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
                    status.update(f"[bold red]❌ Error deleting {image_id[:12]}: {str(e)[:30]}[/bold red]")
                    break
            
            if deleted_count > 0:
                status.update(f"[bold green]✅ Deleted {deleted_count} images ({format_size(deleted_size)} freed)[/bold green]")
                self.selected_images.clear()
                self.run_scan_sync()  # Refresh the table
                self.update_dashboard()  # Update stats
            
        except docker.errors.DockerException as e:
            status.update(f"[bold red]❌ Docker error: {str(e)[:50]}[/bold red]")

    def delete_all_unused(self):
        """Delete all unused images without manual selection."""
        status = self.query_one("#delete_status")
        status.update("🗑️ Deleting ALL unused images...")
        
        try:
            # Run the actual cleanup
            daemon.cleanup_images(dry_run=False)
            status.update("[bold green]✅ Cleanup completed! Check logs for details.[/bold green]")
            self.run_scan_sync()  # Refresh table
            self.update_dashboard()  # Update stats
        except Exception as e:
            status.update(f"[bold red]❌ Error during cleanup: {str(e)[:50]}[/bold red]")

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
                status.update("[bold yellow]📋 No backup data found.[/bold yellow]")
                return
            
            total_size = sum(img.get("size", 0) for img in images)
            # Format timestamp nicely
            try:
                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                time_str = dt.strftime("%Y-%m-%d %H:%M")
            except:
                time_str = timestamp
                
            status.update(f"[bold green]📋 Last backup: {time_str} - {len(images)} images ({format_size(total_size)})[/bold green]")
            
        except FileNotFoundError:
            status.update("[bold yellow]📋 No backup file found.[/bold yellow]")
        except Exception as e:
            status.update(f"[bold red]❌ Error reading backup: {str(e)[:50]}[/bold red]")

if __name__ == "__main__":
    app = DockerJanitorApp()
    app.run()