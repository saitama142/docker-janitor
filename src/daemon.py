
import time
import docker
from datetime import datetime, timedelta, timezone
import logging

from . import config

LOG_FILE = "/var/log/docker-janitor.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        # Use logging.StreamHandler() to also print to console for debugging
    ]
)

def get_unused_images(client, age_threshold_days: int):
    """Returns a list of unused images older than the threshold."""
    try:
        images = client.images.list(dangling=False)
        containers = client.containers.list(all=True)
    except docker.errors.DockerException as e:
        logging.error(f"Failed to connect to Docker daemon: {e}")
        return []

    used_image_ids = {container.image.id for container in containers}
    unused_images = []

    threshold_date = datetime.now(timezone.utc) - timedelta(days=age_threshold_days)

    for image in images:
        # An image is unused if no container is using it
        if image.id not in used_image_ids:
            # Docker API returns created time in ISO 8601 format with nanoseconds
            # We need to parse it and make it timezone-aware (UTC)
            created_time_str = image.attrs['Created'].split('.')[0] + 'Z'
            created_time = datetime.fromisoformat(created_time_str.replace('Z', '+00:00'))

            if created_time < threshold_date:
                unused_images.append(image)

    return unused_images

def cleanup_images():
    """Performs the image cleanup process."""
    logging.info("Starting Docker image cleanup cycle.")
    cfg = config.load_config()
    age_threshold = cfg.get("image_age_threshold_days", 30)

    try:
        client = docker.from_env()
        client.ping() # Verify connection
    except docker.errors.DockerException as e:
        logging.error(f"Could not connect to Docker daemon: {e}")
        return

    images_to_delete = get_unused_images(client, age_threshold)

    if not images_to_delete:
        logging.info("No old, unused images to delete.")
        return

    logging.info(f"Found {len(images_to_delete)} images to delete.")

    for image in images_to_delete:
        try:
            tags = image.tags if image.tags else ["<none>"]
            logging.info(f"Deleting image {image.short_id} with tags: {tags}")
            client.images.remove(image.id, force=True) # Force to remove even if tagged
        except docker.errors.APIError as e:
            logging.error(f"Failed to delete image {image.short_id}: {e}")

def run_daemon():
    """The main loop for the daemon process."""
    logging.info("Docker Janitor daemon started.")
    while True:
        cleanup_images()
        
        cfg = config.load_config()
        sleep_interval = cfg.get("daemon_sleep_interval_seconds", 86400)
        logging.info(f"Sleeping for {sleep_interval} seconds...")
        time.sleep(sleep_interval)
