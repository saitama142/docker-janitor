
import typer
from . import daemon
from . import tui

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
