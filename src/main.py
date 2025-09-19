
import typer
import sys
import os

# Add the current directory to Python path for relative imports
if __name__ == "__main__":
    # When running directly, add the parent directory to path
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, current_dir)

# Try relative imports first, fall back to absolute imports
try:
    from . import daemon
    from . import tui
except ImportError:
    import daemon
    import tui

app = typer.Typer()

@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def main(
    is_daemon: bool = typer.Option(False, "--daemon", help="Run the background daemon process."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview what would be deleted without actually deleting.")
):
    """The main entry point for the Docker Janitor application."""
    if is_daemon:
        daemon.run_daemon()
    elif dry_run:
        # Run one-time cleanup in dry-run mode
        daemon.cleanup_images(dry_run=True)
    else:
        # Launch the Textual TUI application
        app = tui.DockerJanitorApp()
        app.run()

if __name__ == "__main__":
    app()
