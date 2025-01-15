from google.cloud import storage
from config import GCS_BUCKET_NAME, USE_GCS, DOWNLOAD_DIR
from google.oauth2 import service_account
import json
import os
import shutil
import logging

logger = logging.getLogger(__name__)

class StorageManager:
    def __init__(self):
        """Initialize storage manager for both GCS and local storage"""
        try:
            # Get credentials from environment
            GCP_SA_CREDENTIALS = os.getenv('GCP_SA_CREDENTIALS')
            if not GCP_SA_CREDENTIALS:
                raise ValueError("GCP credentials not found in environment")
            
            # Initialize with proper credentials
            credentials_info = json.loads(GCP_SA_CREDENTIALS)
            gcs_credentials = service_account.Credentials.from_service_account_info(
                credentials_info,
                scopes=['https://www.googleapis.com/auth/devstorage.full_control']
            )
            self.client = storage.Client(credentials=gcs_credentials)
            self.bucket = self.client.bucket(GCS_BUCKET_NAME)
            logger.info(f"GCS Debug - Successfully initialized with bucket: {self.bucket.name}")
        except Exception as e:
            logger.error(f"GCS Debug - Error initializing GCS client: {str(e)}")
            raise

        # Use SYSTEM_FILES_DIR for json files if set, otherwise fall back to DOWNLOAD_DIR
        self.system_files_dir = os.getenv('SYSTEM_FILES_DIR', DOWNLOAD_DIR)
        
        # Always ensure both directories exist
        self.ensure_local_directory(DOWNLOAD_DIR)
        self.ensure_local_directory(self.system_files_dir)

    def ensure_local_directory(self, path):
        """Ensure a local directory exists"""
        if not os.path.exists(path):
            os.makedirs(path)
            os.chmod(path, 0o777)  # Ensure directory is writable

    def save_file(self, source_path, destination_path):
        """
        Save a file using appropriate storage method based on path.
        Downloads (video/audio files) go to GCS, system files stay local.
        
        Args:
            source_path: local path where file currently exists
            destination_path: path where file should be stored (without /files/ prefix)
        
        Returns:
            str: Path to access the saved file (/files/...)
        """
        # Determine if this is a download file that should go to GCS
        is_download = any(x in destination_path.lower() for x in [
            'video', 'audio', '.mp4', '.mp3', '.m4a', '.wav'
        ])
        
        if is_download:
            try:
                logger.info(f"GCS Debug - Saving download file to GCS:")
                logger.info(f"  Source path: {source_path}")
                logger.info(f"  Destination path: {destination_path}")
                
                blob = self.bucket.blob(destination_path)
                blob.upload_from_filename(source_path)
                
                logger.info(f"GCS Debug - File saved successfully to GCS")
                logger.info(f"  Blob name: {blob.name}")
                logger.info(f"  Blob size: {blob.size}")
                return f'/files/{destination_path}'
            except Exception as e:
                logger.error(f"GCS Debug - Error saving file to GCS: {str(e)}")
                raise
        else:
            # For system files, save locally
            dest_full_path = os.path.join(DOWNLOAD_DIR, destination_path)
            os.makedirs(os.path.dirname(dest_full_path), exist_ok=True)
            shutil.copy2(source_path, dest_full_path)
            return f'/files/{destination_path}'

    def save_system_file(self, file_path, content):
        """
        Save a system file (like JSON configs) without treating it as a download
        Args:
            file_path: Path where to save the file
            content: String content to save
        Returns:
            str: Path to access the saved file
        """
        try:
            # Use system_files_dir instead of DOWNLOAD_DIR
            full_path = os.path.join(self.system_files_dir, file_path)
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, 'w') as f:
                f.write(content)
            logger.info(f"System file saved locally: {full_path}")
            return f'/files/{file_path}'
        except Exception as e:
            logger.error(f"Error saving system file {file_path}: {str(e)}")
            raise

    def get_system_file(self, file_path):
        """
        Get a system file content always from local storage
        Args:
            file_path: Path to the file
        Returns:
            str: File content or None if not found
        """
        try:
            # Use system_files_dir instead of DOWNLOAD_DIR
            full_path = os.path.join(self.system_files_dir, file_path)
            if os.path.exists(full_path):
                with open(full_path, 'r') as f:
                    return f.read()
            logger.warning(f"File not found locally: {full_path}")
            return None
        except Exception as e:
            logger.error(f"Error reading system file {file_path}: {str(e)}")
            return None

    def get_file(self, file_path):
        """
        Get a file from storage.
        
        Args:
            file_path: Path to the file (with or without /files/ prefix)
            
        Returns:
            Union[storage.Blob, str, None]: GCS blob object or local file path, None if not found
        """
        # Remove /files/ prefix if present
        clean_path = file_path.replace('/files/', '')
        
        # Check if this is a download file that should be in GCS
        is_download = any(x in clean_path.lower() for x in [
            'video', 'audio', '.mp4', '.mp3', '.m4a', '.wav'
        ])
        
        if is_download:
            blob = self.bucket.blob(clean_path)
            if not blob.exists():
                return None
            return blob
        else:
            # For system files, check system_files_dir first, then fallback to download_dir
            full_path = os.path.join(self.system_files_dir, clean_path)
            if os.path.exists(full_path):
                return full_path
            
            # Fallback to download dir
            full_path = os.path.join(DOWNLOAD_DIR, clean_path)
            if os.path.exists(full_path):
                return full_path
            return None

    def delete_file(self, file_path):
        """
        Delete a file from appropriate storage location
        
        Args:
            file_path: Path to the file (with or without /files/ prefix)
        """
        clean_path = file_path.replace('/files/', '')
        is_download = any(x in clean_path.lower() for x in [
            'video', 'audio', '.mp4', '.mp3', '.m4a', '.wav'
        ])
        
        if is_download:
            blob = self.bucket.blob(clean_path)
            if blob.exists():
                blob.delete()
        else:
            # Check system_files_dir first
            full_path = os.path.join(self.system_files_dir, clean_path)
            if os.path.exists(full_path):
                os.remove(full_path)
                return
            
            # Fallback to download dir
            full_path = os.path.join(DOWNLOAD_DIR, clean_path)
            if os.path.exists(full_path):
                os.remove(full_path)

    def delete_directory(self, directory_path):
        """
        Delete a directory and all its contents from appropriate storage
        
        Args:
            directory_path: Directory path to delete
        """
        clean_path = directory_path.replace('/files/', '')
        
        # Always try to clean up GCS in case there are any download files
        blobs = self.bucket.list_blobs(prefix=clean_path)
        for blob in blobs:
            blob.delete()
            
        # Try to clean up in system_files_dir
        full_path = os.path.join(self.system_files_dir, clean_path)
        if os.path.exists(full_path):
            shutil.rmtree(full_path, ignore_errors=True)
            
        # Try to clean up in download dir
        full_path = os.path.join(DOWNLOAD_DIR, clean_path)
        if os.path.exists(full_path):
            shutil.rmtree(full_path, ignore_errors=True)

    def list_task_files(self, task_id):
        """
        List all files associated with a task
        
        Args:
            task_id: ID of the task
            
        Returns:
            list: List of file names
        """
        files = []
        
        # List files from GCS
        blobs = self.bucket.list_blobs(prefix=task_id)
        for blob in blobs:
            files.append(blob.name)
        
        # List files from system_files_dir
        task_dir = os.path.join(self.system_files_dir, task_id)
        if os.path.exists(task_dir):
            local_files = os.listdir(task_dir)
            files.extend([f'{task_id}/{f}' for f in local_files])
            
        # List files from download dir
        task_dir = os.path.join(DOWNLOAD_DIR, task_id)
        if os.path.exists(task_dir):
            local_files = os.listdir(task_dir)
            files.extend([f'{task_id}/{f}' for f in local_files])
        
        return list(set(files))  # Remove duplicates