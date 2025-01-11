from google.cloud import storage
from config import GCS_BUCKET_NAME, USE_GCS, DOWNLOAD_DIR
import os
import shutil

class StorageManager:
    def __init__(self):
        if USE_GCS:
            self.client = storage.Client()
            self.bucket = self.client.bucket(GCS_BUCKET_NAME)

    def ensure_local_directory(self, path):
        """Ensure a local directory exists"""
        if not os.path.exists(path):
            os.makedirs(path)

    def save_file(self, source_path, destination_path):
        """
        Save a file to either GCS or local storage.
        source_path: local path where file currently exists
        destination_path: path where file should be stored (without /files/ prefix)
        """
        if USE_GCS:
            blob = self.bucket.blob(destination_path)
            blob.upload_from_filename(source_path)
            return f'/files/{destination_path}'
        else:
            dest_full_path = os.path.join(DOWNLOAD_DIR, destination_path)
            os.makedirs(os.path.dirname(dest_full_path), exist_ok=True)
            shutil.copy2(source_path, dest_full_path)
            return f'/files/{destination_path}'

    def get_file(self, file_path):
        """Get a file from storage"""
        if USE_GCS:
            # Remove /files/ prefix if present
            clean_path = file_path.replace('/files/', '')
            blob = self.bucket.blob(clean_path)
            if not blob.exists():
                return None
            return blob
        else:
            full_path = os.path.join(DOWNLOAD_DIR, file_path.replace('/files/', ''))
            if os.path.exists(full_path):
                return full_path
            return None

    def delete_file(self, file_path):
        """Delete a file from storage"""
        if USE_GCS:
            clean_path = file_path.replace('/files/', '')
            blob = self.bucket.blob(clean_path)
            if blob.exists():
                blob.delete()
        else:
            full_path = os.path.join(DOWNLOAD_DIR, file_path.replace('/files/', ''))
            if os.path.exists(full_path):
                os.remove(full_path)

    def delete_directory(self, directory_path):
        """Delete a directory and all its contents"""
        if USE_GCS:
            clean_path = directory_path.replace('/files/', '')
            blobs = self.bucket.list_blobs(prefix=clean_path)
            for blob in blobs:
                blob.delete()
        else:
            full_path = os.path.join(DOWNLOAD_DIR, directory_path.replace('/files/', ''))
            if os.path.exists(full_path):
                shutil.rmtree(full_path, ignore_errors=True)

    def save_task_file(self, task_id, filename, file_data):
        """Save a file associated with a specific task"""
        destination_path = f'{task_id}/{filename}'
        if USE_GCS:
            blob = self.bucket.blob(destination_path)
            blob.upload_from_string(file_data)
            return f'/files/{destination_path}'
        else:
            full_path = os.path.join(DOWNLOAD_DIR, destination_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'w') as f:
                f.write(file_data)
            return f'/files/{destination_path}'

    def list_task_files(self, task_id):
        """List all files associated with a task"""
        if USE_GCS:
            files = []
            blobs = self.bucket.list_blobs(prefix=task_id)
            for blob in blobs:
                files.append(blob.name)
            return files
        else:
            task_dir = os.path.join(DOWNLOAD_DIR, task_id)
            if os.path.exists(task_dir):
                return os.listdir(task_dir)
            return []