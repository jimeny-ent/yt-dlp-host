# Standard library imports
import json
import logging
import os
import shutil
import threading
import time
import atexit
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

# Third-party imports
import requests
import yt_dlp
from flask import current_app, request
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
from yt_dlp.utils import download_range_func

# Local application imports
from config import (
    DOWNLOAD_DIR,
    GCS_BUCKET_NAME,
    MAX_WORKERS,
    TASK_CLEANUP_TIME,
    USE_GCS,
)
from src.auth import check_memory_limit
from src.json_utils import load_tasks, save_tasks, load_keys
from src.storage_utils import StorageManager

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize global objects
executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
storage_manager = StorageManager()

# Ensure download directory exists
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

def handle_task_error(task_id, error):
    """Handle task errors by updating task status and logging"""
    logger.error(f"Error in task {task_id}: {str(error)}")
    try:
        tasks = load_tasks()
        if task_id in tasks:
            tasks[task_id].update({
                'status': 'failed',
                'error': str(error),
                'completed_time': datetime.now().isoformat()
            })
            save_tasks(tasks)
    except Exception as e:
        logger.error(f"Error updating task status: {str(e)}")

def check_and_get_size(url, video_format=None, audio_format=None):
    """Estimate the size of the download"""
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'format': f'{video_format}+{audio_format}/best' if video_format else f'{audio_format}/best'
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if 'requested_formats' in info:
                # For merged formats (video + audio)
                total_size = sum(f.get('filesize', 0) or f.get('filesize_approx', 0) 
                               for f in info['requested_formats'])
            else:
                # For single format
                total_size = info.get('filesize', 0) or info.get('filesize_approx', 0)
            
            # Add 10% buffer for safety
            return int(total_size * 1.1)
    except Exception as e:
        logger.error(f"Error estimating file size: {str(e)}")
        return 0

def get_public_url(file_path, bucket_name):
    """Generate a public GCS URL for the file"""
    clean_path = file_path.replace('/files/', '')
    return f"https://storage.googleapis.com/{bucket_name}/{clean_path}"

def notify_webhook(webhook_url, data, max_retries=3, initial_delay=1):
    """Enhanced webhook notification with exponential backoff"""
    logger = logging.getLogger(__name__)
    
    # Configure session with retry strategy
    session = requests.Session()
    retry_strategy = Retry(
        total=max_retries,
        backoff_factor=2,  # exponential backoff
        status_forcelist=[408, 429, 500, 502, 503, 504],
        allowed_methods=["POST"]  # Explicitly allow POST for retries
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    try:
        response = session.post(
            webhook_url, 
            json=data,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        response.raise_for_status()
        logger.info(f"Webhook notification successful: {response.status_code}")
        return True
    except requests.exceptions.RequestException as e:
        logger.error(f"Webhook notification failed after {max_retries} retries: {str(e)}")
        return False

def send_webhook_notification(task_id, file_path, base_url=None):
    """Enhanced webhook notification handler"""
    logger = logging.getLogger(__name__)
    tasks = load_tasks()
    task = tasks.get(task_id)
    
    if not task or not task.get('webhook_url'):
        logger.warning(f"No webhook URL found for task {task_id}")
        return
    
    try:
        # Generate the appropriate file URL based on storage type
        if USE_GCS:
            file_url = get_public_url(file_path, GCS_BUCKET_NAME)
        else:
            if base_url is None:
                base_url = os.environ.get('APP_BASE_URL', 'http://localhost:5000')
            file_url = f"{base_url.rstrip('/')}{file_path}"
        
        webhook_data = {
            'status': 'completed',
            'task_id': task_id,
            'file_url': file_url,
            'task_type': task.get('task_type', 'unknown'),
            'original_url': task.get('url'),
            'completion_time': datetime.now().isoformat(),
            'storage_type': 'gcs' if USE_GCS else 'local'
        }
        
        logger.info(f"Sending webhook for task {task_id} to {task['webhook_url']}")
        success = notify_webhook(task['webhook_url'], webhook_data)
        
        if not success:
            # Update task status to reflect webhook failure
            tasks[task_id].update({
                'webhook_status': 'failed',
                'webhook_error': 'Failed to send webhook notification'
            })
            save_tasks(tasks)
            
    except Exception as e:
        logger.error(f"Error in webhook notification for task {task_id}: {str(e)}")
        # Update task status
        tasks[task_id].update({
            'webhook_status': 'failed',
            'webhook_error': str(e)
        })
        save_tasks(tasks)

def cleanup_processing_tasks():
    """Clean up tasks that have been processing for too long"""
    try:
        tasks = load_tasks()
        current_time = datetime.now()
        
        for task_id, task in list(tasks.items()):
            if task['status'] == 'processing':
                # Check if task has been processing for too long
                started_time = datetime.fromisoformat(task.get('started_time', '2000-01-01T00:00:00'))
                if current_time - started_time > timedelta(minutes=TASK_CLEANUP_TIME):
                    logger.warning(f"Cleaning up stalled task {task_id}")
                    cleanup_task(task_id)
    except Exception as e:
        logger.error(f"Error in cleanup_processing_tasks: {str(e)}")

def process_tasks():
    """Background task processor"""
    logger.info("Starting task processor")
    while True:
        try:
            tasks = load_tasks()
            for task_id, task in list(tasks.items()):
                if task['status'] == 'waiting':
                    # Update task status
                    tasks[task_id].update({
                        'status': 'processing',
                        'started_time': datetime.now().isoformat()
                    })
                    save_tasks(tasks)
                    
                    # Process based on task type
                    if task['task_type'] == 'get_video':
                        executor.submit(
                            get,
                            task_id,
                            task['url'],
                            'video',
                            task.get('video_format', 'bestvideo'),
                            task.get('audio_format', 'bestaudio')
                        )
                    elif task['task_type'] == 'get_audio':
                        executor.submit(
                            get,
                            task_id,
                            task['url'],
                            'audio',
                            None,
                            task.get('audio_format', 'bestaudio')
                        )
                    elif task['task_type'] == 'get_info':
                        executor.submit(get_info, task_id, task['url'])
                    elif task['task_type'] == 'get_live_video':
                        executor.submit(
                            get_live,
                            task_id,
                            task['url'],
                            'video',
                            task.get('start', 0),
                            task.get('duration', 300),
                            task.get('video_format', 'bestvideo'),
                            task.get('audio_format', 'bestaudio')
                        )
                    elif task['task_type'] == 'get_live_audio':
                        executor.submit(
                            get_live,
                            task_id,
                            task['url'],
                            'audio',
                            task.get('start', 0),
                            task.get('duration', 300),
                            None,
                            task.get('audio_format', 'bestaudio')
                        )
            
            # Cleanup old tasks
            cleanup_processing_tasks()
            time.sleep(1)  # Prevent CPU overuse
            
        except Exception as e:
            logger.error(f"Error in process_tasks: {str(e)}")
            time.sleep(5)  # Wait before retrying
    
def get_info(task_id, url):
    try:
        tasks = load_tasks()
        tasks[task_id].update(status='processing')
        save_tasks(tasks)

        temp_path = os.path.join(DOWNLOAD_DIR, task_id)
        os.makedirs(temp_path, exist_ok=True)
        os.chmod(temp_path, 0o777)

        ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True, 'skip_download': True}

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            info_file = os.path.join(temp_path, 'info.json')
            with open(info_file, 'w') as f:
                json.dump(info, f)

            # Upload to storage and get the path
            stored_path = storage_manager.save_file(info_file, f'{task_id}/info.json')

            tasks = load_tasks()
            tasks[task_id].update(status='completed')
            tasks[task_id]['completed_time'] = datetime.now().isoformat()
            tasks[task_id]['file'] = stored_path
            save_tasks(tasks)

            # Send webhook notification
            send_webhook_notification(task_id, stored_path)

            # Clean up temp files
            shutil.rmtree(temp_path, ignore_errors=True)
        except Exception as e:
            handle_task_error(task_id, e)
    except Exception as e:
        handle_task_error(task_id, e)

def get(task_id, url, type, video_format="bestvideo", audio_format="bestaudio"):
    try:
        tasks = load_tasks()
        tasks[task_id].update(status='processing')
        save_tasks(tasks)

        logger.info(f"Starting download for task {task_id} - URL: {url}")
        
        # Create base temp directory with full permissions
        temp_path = os.path.join(DOWNLOAD_DIR, task_id)
        os.makedirs(temp_path, exist_ok=True)
        os.chmod(temp_path, 0o777)

        output_template = 'video.%(ext)s' if type.lower() == 'video' else 'audio.%(ext)s'
        
        # Define a progress hook that ensures directory exists for fragments
        def ensure_fragment_dir(d):
            if d.get('filename'):
                frag_dir = os.path.dirname(d['filename'])
                if frag_dir and not os.path.exists(frag_dir):
                    os.makedirs(frag_dir, exist_ok=True)
                    os.chmod(frag_dir, 0o777)
            logger.info(f"Download progress: {d.get('status')} - {d.get('filename', 'unknown')}")

        ydl_opts = {
            'format': f'{video_format}+{audio_format}/best' if type.lower() == 'video' else f'{audio_format}/best',
            'outtmpl': os.path.join(temp_path, output_template),
            'merge_output_format': 'mp4' if type.lower() == 'video' else None,
            'allow_unplayable_formats': True,
            'no_check_certificate': True,
            'verbose': True,
            'progress_hooks': [ensure_fragment_dir],
            'concurrent_fragments': 3,
            'retries': 10,  # Increase retries
            'fragment_retries': 10,  # Add fragment retries
            'continuedl': True,  # Continue partial downloads
            'buffersize': 1024  # Reduced buffer size for more stable downloads
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            # Get the downloaded file
            downloaded_files = [f for f in os.listdir(temp_path) if not f.endswith('.part')]
            if not downloaded_files:
                raise Exception("No complete files found after download")
                
            downloaded_file = downloaded_files[0]
            local_file_path = os.path.join(temp_path, downloaded_file)
            
            # Upload to GCS
            stored_path = storage_manager.save_file(
                local_file_path, 
                f'{task_id}/{downloaded_file}'
            )
            
            # Update task status
            tasks = load_tasks()
            tasks[task_id].update({
                'status': 'completed',
                'completed_time': datetime.now().isoformat(),
                'file': stored_path
            })
            save_tasks(tasks)
            
            # Clean up temp directory
            shutil.rmtree(temp_path, ignore_errors=True)
            
            # Send webhook notification
            send_webhook_notification(task_id, stored_path)
            
        except Exception as e:
            logger.error(f"Download error: {str(e)}")
            handle_task_error(task_id, str(e))
            
    except Exception as e:
        logger.error(f"Task error: {str(e)}")
        handle_task_error(task_id, str(e))

def get_live(task_id, url, type, start, duration, video_format="bestvideo", audio_format="bestaudio"):
    try:
        tasks = load_tasks()
        tasks[task_id].update(status='processing')
        save_tasks(tasks)
        
        temp_path = os.path.join(DOWNLOAD_DIR, task_id)
        os.makedirs(temp_path, exist_ok=True)
        os.chmod(temp_path, 0o777)

        current_time = int(time.time())
        start_time = current_time - start
        end_time = start_time + duration

        output_template = 'live_video.%(ext)s' if type.lower() == 'video' else 'live_audio.%(ext)s'
        format_option = f'{video_format}+{audio_format}' if type.lower() == 'video' else audio_format

        ydl_opts = {
            'format': format_option,
            'outtmpl': os.path.join(temp_path, output_template),
            'download_ranges': lambda info, *args: [{'start_time': start_time, 'end_time': end_time,}],
            'merge_output_format': 'mp4' if type.lower() == 'video' else None
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            # Get the downloaded file name
            downloaded_file = os.listdir(temp_path)[0]
            local_file_path = os.path.join(temp_path, downloaded_file)
            
            # Upload to storage and get the path
            stored_path = storage_manager.save_file(
                local_file_path, 
                f'{task_id}/{downloaded_file}'
            )

            tasks = load_tasks()
            tasks[task_id].update(status='completed')
            tasks[task_id]['completed_time'] = datetime.now().isoformat()
            tasks[task_id]['file'] = stored_path
            save_tasks(tasks)

            # Send webhook notification
            send_webhook_notification(task_id, stored_path)

            # Clean up temp files
            shutil.rmtree(temp_path, ignore_errors=True)

        except Exception as e:
            handle_task_error(task_id, e)
    except Exception as e:
        handle_task_error(task_id, e)

def cleanup_task(task_id):
    tasks = load_tasks()
    
    # Delete files from storage
    storage_manager.delete_directory(task_id)
    
    # Clean up local temp directory if it exists
    temp_path = os.path.join(DOWNLOAD_DIR, task_id)
    if os.path.exists(temp_path):
        shutil.rmtree(temp_path, ignore_errors=True)
    
    if task_id in tasks:
        del tasks[task_id]
        save_tasks(tasks)

def cleanup_orphaned_folders():
    tasks = load_tasks()
    task_ids = set(tasks.keys())
    
    # Clean up local folders
    for folder in os.listdir(DOWNLOAD_DIR):
        folder_path = os.path.join(DOWNLOAD_DIR, folder)
        if os.path.isdir(folder_path) and folder not in task_ids:
            shutil.rmtree(folder_path, ignore_errors=True)
            logger.info(f"Removed orphaned local folder: {folder_path}")

    if USE_GCS:
        # Clean up GCS folders
        blobs = storage_manager.bucket.list_blobs()
        for blob in blobs:
            task_id = blob.name.split('/')[0]
            if task_id not in task_ids:
                blob.delete()
                logger.info(f"Removed orphaned GCS file: {blob.name}")

def cleanup():
    """Cleanup function to shutdown the executor properly"""
    logger.info("Shutting down executor...")
    executor.shutdown(wait=True)
    logger.info("Executor shutdown complete")

def init_background_tasks():
    """Initialize background tasks and return the thread"""
    logger.info("Initializing background tasks...")
    cleanup_processing_tasks()
    cleanup_orphaned_folders()
    thread = threading.Thread(target=process_tasks, daemon=True)
    thread.start()
    logger.info("Background tasks initialized")
    return thread

# Register cleanup
atexit.register(cleanup)

# Initialize background tasks
background_thread = None

if __name__ == '__main__':
    background_thread = init_background_tasks()
else:
    # For production/gunicorn environment
    background_thread = init_background_tasks()