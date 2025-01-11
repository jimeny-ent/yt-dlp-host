from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from config import DOWNLOAD_DIR, TASK_CLEANUP_TIME, MAX_WORKERS
from src.json_utils import load_tasks, save_tasks, load_keys
from src.auth import check_memory_limit
import yt_dlp, os, threading, json, time, shutil
from yt_dlp.utils import download_range_func

executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

def get_format_size(info, format_id):
    for f in info.get('formats', []):
        if f.get('format_id') == format_id:
            return f.get('filesize') or f.get('filesize_approx', 0)
    return 0

def get_best_format_size(info, formats, formats_list, is_video=True):
    if not formats_list:
        return 0
    formats_with_size = [f for f in formats_list if (f.get('filesize') or f.get('filesize_approx', 0)) > 0]
    
    if formats_with_size:
        if is_video:
            return max(formats_with_size, 
                        key=lambda f: (f.get('height', 0), f.get('tbr', 0)))
        else:
            return max(formats_with_size, 
                        key=lambda f: (f.get('abr', 0) or f.get('tbr', 0)))
    
    best_format = max(formats_list, 
                    key=lambda f: (f.get('height', 0), f.get('tbr', 0)) if is_video 
                    else (f.get('abr', 0) or f.get('tbr', 0)))
    
    if best_format.get('tbr'):
        estimated_size = int(best_format['tbr'] * info.get('duration', 0) * 128 * 1024 / 8)
        if estimated_size > 0:
            return best_format
    
    similar_formats = [f for f in formats if f.get('height', 0) == best_format.get('height', 0)] if is_video \
                    else [f for f in formats if abs(f.get('abr', 0) - best_format.get('abr', 0)) < 50]
    
    sizes = [f.get('filesize') or f.get('filesize_approx', 0) for f in similar_formats]
    if sizes and any(sizes):
        best_format['filesize_approx'] = max(s for s in sizes if s > 0)
        return best_format
    
    return best_format

def check_and_get_size(url, video_format=None, audio_format=None):
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'skip_download': True,
            'format': 'bestvideo+bestaudio/best',
            'allow_unplayable_formats': True,
            'no_check_certificate': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': '*/*',
                'Accept-Encoding': 'gzip, deflate, br',
                'Origin': 'https://cloudflarestream.com',
                'Referer': 'https://cloudflarestream.com/'
            }
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # For DASH/MPD manifests from Cloudflare Stream
            if 'formats' in info:
                formats = info['formats']
                total_size = 0
                
                if video_format:
                    video_formats = [f for f in formats if f.get('vcodec') != 'none']
                    if video_formats:
                        best_video = max(video_formats, 
                                      key=lambda f: (f.get('height', 0) or 0, f.get('tbr', 0) or 0))
                        if best_video.get('filesize') or best_video.get('filesize_approx'):
                            total_size += best_video.get('filesize') or best_video.get('filesize_approx')
                        elif best_video.get('tbr'):
                            # Estimate from bitrate and duration
                            total_size += int((best_video['tbr'] * 1024 * info.get('duration', 300)) / 8)
                
                if audio_format:
                    audio_formats = [f for f in formats if f.get('acodec') != 'none']
                    if audio_formats:
                        best_audio = max(audio_formats,
                                      key=lambda f: f.get('tbr', 0) or 0)
                        if best_audio.get('filesize') or best_audio.get('filesize_approx'):
                            total_size += best_audio.get('filesize') or best_audio.get('filesize_approx')
                        elif best_audio.get('tbr'):
                            # Estimate from bitrate and duration
                            total_size += int((best_audio['tbr'] * 128 * info.get('duration', 300)) / 8)
                
                # Add 20% buffer for MPD overhead
                if total_size > 0:
                    return int(total_size * 1.2)

            # Default size for unknown formats
            return 100 * 1024 * 1024  # 100MB default

    except Exception as e:
        print(f"Error in check_and_get_size: {str(e)}")
        return 100 * 1024 * 1024  # Return default size instead of -1

def get_info(task_id, url):
    try:
        tasks = load_tasks()
        tasks[task_id].update(status='processing')
        save_tasks(tasks)

        download_path = os.path.join(DOWNLOAD_DIR, task_id)
        if not os.path.exists(download_path):
            os.makedirs(download_path)

        ydl_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True, 'skip_download': True}

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

            info_file = os.path.join(DOWNLOAD_DIR, task_id, f'info.json')
            os.makedirs(os.path.dirname(info_file), exist_ok=True)
            with open(info_file, 'w') as f:
                json.dump(info, f)

            tasks = load_tasks()
            tasks[task_id].update(status='completed')
            tasks[task_id]['completed_time'] = datetime.now().isoformat()
            tasks[task_id]['file'] = f'/files/{task_id}/info.json'
            save_tasks(tasks)
        except Exception as e:
            handle_task_error(task_id, e)
    except Exception as e:
        handle_task_error(task_id, e)

def get(task_id, url, type, video_format="bestvideo", audio_format="bestaudio"):
    try:
        tasks = load_tasks()
        tasks[task_id].update(status='processing')
        save_tasks(tasks)

        # Get size estimate but don't fail on error
        total_size = check_and_get_size(url, video_format if type.lower() == 'video' else None, audio_format)
        
        key_name = tasks[task_id].get('key_name')
        keys = load_keys()
        if key_name not in keys:
            handle_task_error(task_id, "Invalid API key")
            return
        api_key = keys[key_name]['key']

        if not check_memory_limit(api_key, total_size, task_id):
            raise Exception("Memory limit exceeded. Maximum 5GB per 10 minutes.")
        
        download_path = os.path.join(DOWNLOAD_DIR, task_id)
        if not os.path.exists(download_path):
            os.makedirs(download_path)

        ydl_opts = {
            'format': f'{video_format}+{audio_format}/best' if type.lower() == 'video' else f'{audio_format}/best',
            'outtmpl': os.path.join(download_path, 'video.%(ext)s' if type.lower() == 'video' else 'audio.%(ext)s'),
            'merge_output_format': 'mp4' if type.lower() == 'video' else None,
            'allow_unplayable_formats': True,
            'no_check_certificate': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': '*/*',
                'Accept-Encoding': 'gzip, deflate, br',
                'Origin': 'https://cloudflarestream.com',
                'Referer': 'https://cloudflarestream.com/'
            },
            'verbose': True,
            # Support for DASH manifests
            'external_downloader_args': ['--no-check-certificate'],
            'concurrent_fragments': 5
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            tasks = load_tasks()
            tasks[task_id].update(status='completed')
            tasks[task_id]['completed_time'] = datetime.now().isoformat()
            tasks[task_id]['file'] = f'/files/{task_id}/' + os.listdir(download_path)[0]
            save_tasks(tasks)
            
        except Exception as e:
            print(f"Download error: {str(e)}")
            handle_task_error(task_id, str(e))
            
    except Exception as e:
        print(f"Task error: {str(e)}")
        handle_task_error(task_id, str(e))

def get_live(task_id, url, type, start, duration, video_format="bestvideo", audio_format="bestaudio"):
    try:
        tasks = load_tasks()
        tasks[task_id].update(status='processing')
        save_tasks(tasks)
        
        download_path = os.path.join(DOWNLOAD_DIR, task_id)
        if not os.path.exists(download_path):
            os.makedirs(download_path)

        current_time = int(time.time())
        start_time = current_time - start
        end_time = start_time + duration

        if type.lower() == 'audio':
            format_option = f'{audio_format}'
            output_template = f'live_audio.%(ext)s'
        else:
            format_option = f'{video_format}+{audio_format}'
            output_template = f'live_video.%(ext)s'

        ydl_opts = {
            'format': format_option,
            'outtmpl': os.path.join(download_path, output_template),
            'download_ranges': lambda info, *args: [{'start_time': start_time, 'end_time': end_time,}],
            'merge_output_format': 'mp4' if type.lower() == 'video' else None
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            tasks = load_tasks()
            tasks[task_id].update(status='completed')
            tasks[task_id]['completed_time'] = datetime.now().isoformat()
            tasks[task_id]['file'] = f'/files/{task_id}/' + os.listdir(download_path)[0]
            save_tasks(tasks)
        except Exception as e:
            handle_task_error(task_id, e)
    except Exception as e:
        handle_task_error(task_id, e)

def handle_task_error(task_id, error):
    tasks = load_tasks()
    tasks[task_id].update(status='error', error=str(error), completed_time=datetime.now().isoformat())
    save_tasks(tasks)
    print(f"Error in task {task_id}: {str(error)}")

def cleanup_task(task_id):
    tasks = load_tasks()
    download_path = os.path.join(DOWNLOAD_DIR, task_id)
    if os.path.exists(download_path):
        shutil.rmtree(download_path, ignore_errors=True)
    if task_id in tasks:
        del tasks[task_id]
        save_tasks(tasks)

def cleanup_orphaned_folders():
    tasks = load_tasks()
    task_ids = set(tasks.keys())
    
    for folder in os.listdir(DOWNLOAD_DIR):
        folder_path = os.path.join(DOWNLOAD_DIR, folder)
        if os.path.isdir(folder_path) and folder not in task_ids:
            shutil.rmtree(folder_path, ignore_errors=True)
            print(f"Removed orphaned folder: {folder_path}")

def cleanup_processing_tasks():
    tasks = load_tasks()
    for task_id, task in list(tasks.items()):
        if task['status'] == 'processing':
            task['status'] = 'error'
            task['error'] = 'Task was interrupted during processing'
            task['completed_time'] = datetime.now().isoformat()
    save_tasks(tasks)

def process_tasks():
    while True:
        tasks = load_tasks()
        current_time = datetime.now()
        for task_id, task in list(tasks.items()):
            if task['status'] == 'waiting':
                if task['task_type'] == 'get_video':
                    executor.submit(get, task_id, task['url'], 'video', task['video_format'], task['audio_format'])
                elif task['task_type'] == 'get_audio':
                    executor.submit(get, task_id, task['url'], 'audio', 'bestvideo', task['audio_format'])
                elif task['task_type'] == 'get_info':
                    executor.submit(get_info, task_id, task['url'])
                elif task['task_type'] == 'get_live_video':
                    executor.submit(get_live, task_id, task['url'], 'video', task['start'], task['duration'], task['video_format'], task['audio_format'])
                elif task['task_type'] == 'get_live_audio':
                    executor.submit(get_live, task_id, task['url'], 'audio', task['start'], task['duration'], 'bestvideo', task['audio_format'])
            elif task['status'] in ['completed', 'error']:
                completed_time = datetime.fromisoformat(task['completed_time'])
                if current_time - completed_time > timedelta(minutes=TASK_CLEANUP_TIME):
                    cleanup_task(task_id)
        if current_time.minute % 5 == 0 and current_time.second == 0:
            cleanup_orphaned_folders()
        time.sleep(1)

cleanup_processing_tasks()
cleanup_orphaned_folders()
thread = threading.Thread(target=process_tasks, daemon=True)
thread.start()
