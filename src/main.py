
import typer
from . import daemon
from . import tui

app = typer.Typer()

@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def main(is_daemon: bool = typer.Option(False, "--daemon", help="Run the background daemon process.")):
    """The main entry point for the Docker Janitor application."""
    if is_daemon:
        daemon.run_daemon()
    else:
        # Launch the Textual TUI application
        app = tui.DockerJanitorApp()
        app.run()

if __name__ == "__main__":
    app()
