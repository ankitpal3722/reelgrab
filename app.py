#!/usr/bin/env python3
"""
Instagram Reel Downloader — Web App
Flask backend wrapping InstaReelDownloader with SSE progress and zip packaging.
"""

import instaloader
import os
import sys
import uuid
import json
import shutil
import zipfile
import threading
import time
from pathlib import Path
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, Response, send_file, stream_with_context

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Store active tasks: task_id -> {status, progress, messages, zip_path, ...}
tasks = {}
# Lock for thread-safe task access
tasks_lock = threading.Lock()

# Cleanup old tasks after this many seconds
TASK_TTL_SECONDS = 1800  # 30 minutes
DOWNLOAD_DIR = Path("/tmp/insta_downloads")


class WebReelDownloader:
    """Wrapper around instaloader with progress callbacks for the web UI."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        self.loader = instaloader.Instaloader(
            download_videos=True,
            download_video_thumbnails=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            download_pictures=False,
            download_geotags=False,
        )
        self.task_dir = DOWNLOAD_DIR / task_id
        self.videos_dir = self.task_dir / "videos"
        self.videos_dir.mkdir(parents=True, exist_ok=True)

    def _update(self, **kwargs):
        """Thread-safe task status update."""
        with tasks_lock:
            tasks[self.task_id].update(kwargs)

    def _add_message(self, msg: str):
        with tasks_lock:
            tasks[self.task_id]["messages"].append(msg)

    def sanitize_filename(self, filename: str) -> str:
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        if len(filename) > 200:
            filename = filename[:200]
        return filename.strip()

    def download_reels(self, username: str):
        """Download all reels and build a zip."""
        try:
            self._update(status="fetching", progress=0)
            self._add_message(f"🔍 Fetching profile @{username}...")

            profile = instaloader.Profile.from_username(self.loader.context, username)

            self._add_message(f"📱 {profile.full_name} (@{profile.username})")
            self._add_message(f"👥 {profile.followers:,} followers • {profile.mediacount:,} posts")
            self._update(status="scanning")

            # First pass — count reels
            self._add_message("📊 Scanning for reels...")
            posts = list(profile.get_posts())
            reels = [p for p in posts if p.is_video and p.typename == "GraphVideo"]
            total_reels = len(reels)

            if total_reels == 0:
                self._update(status="error", error="No reels found on this profile.")
                self._add_message("❌ No reels found!")
                return

            self._add_message(f"📹 Found {total_reels} reels. Starting download...")
            self._update(status="downloading", total=total_reels, downloaded=0)

            captions = {}
            downloaded = 0

            for i, post in enumerate(reels):
                try:
                    # Build filename from caption
                    if post.caption:
                        title = post.caption.split('\n')[0]
                        title = ' '.join(w for w in title.split() if not w.startswith('#'))
                        if len(title) > 100:
                            title = title[:100]
                        full_caption = post.caption
                    else:
                        title = post.shortcode
                        full_caption = ""

                    clean_title = self.sanitize_filename(title) or post.shortcode
                    filename = f"{clean_title}.mp4"
                    filepath = self.videos_dir / filename

                    self._add_message(f"⬇️ [{i+1}/{total_reels}] {clean_title[:50]}...")
                    self._update(downloaded=i, progress=int((i / total_reels) * 100))

                    # Download
                    self.loader.download_post(post, target=str(self.videos_dir))

                    # Find and rename
                    patterns = [
                        f"{post.date_utc.strftime('%Y-%m-%d_%H-%M-%S')}_UTC*.mp4",
                        f"*{post.shortcode}*.mp4",
                    ]
                    downloaded_file = None
                    for pattern in patterns:
                        matches = list(self.videos_dir.glob(pattern))
                        if matches:
                            downloaded_file = matches[0]
                            break

                    if downloaded_file and downloaded_file != filepath:
                        if filepath.exists():
                            filepath.unlink()
                        downloaded_file.rename(filepath)

                    # Cleanup extra files
                    for ext in ['txt', 'json', 'xz', 'jpg', 'png']:
                        for pattern in patterns:
                            base_pattern = pattern.replace('.mp4', f'.{ext}')
                            for f in self.videos_dir.glob(base_pattern):
                                f.unlink()

                    # Save caption
                    if full_caption:
                        captions[filename] = full_caption

                    downloaded += 1
                    self._add_message(f"✅ Downloaded: {clean_title[:50]}")

                    # Rate limit
                    time.sleep(2)

                except Exception as e:
                    self._add_message(f"❌ Failed: {str(e)[:80]}")
                    continue

            # Save captions file
            if captions:
                captions_path = self.videos_dir / "captions.json"
                with open(captions_path, "w", encoding="utf-8") as f:
                    json.dump(captions, f, indent=2, ensure_ascii=False)

                # Also save a readable txt
                txt_path = self.videos_dir / "captions.txt"
                with open(txt_path, "w", encoding="utf-8") as f:
                    for fname, caption in captions.items():
                        f.write(f"{'='*60}\n")
                        f.write(f"📹 {fname}\n")
                        f.write(f"{'='*60}\n")
                        f.write(f"{caption}\n\n")

            # Create zip
            self._add_message(f"📦 Zipping {downloaded} videos...")
            self._update(status="zipping", progress=95)

            zip_path = self.task_dir / f"{username}_reels.zip"
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                for file in self.videos_dir.iterdir():
                    zf.write(file, file.name)

            zip_size_mb = zip_path.stat().st_size / (1024 * 1024)
            self._add_message(f"✨ Done! {downloaded}/{total_reels} reels ({zip_size_mb:.1f} MB)")
            self._update(
                status="done",
                progress=100,
                downloaded=downloaded,
                zip_path=str(zip_path),
                zip_size=f"{zip_size_mb:.1f}",
                zip_filename=f"{username}_reels.zip",
            )

        except instaloader.exceptions.ProfileNotExistsException:
            self._update(status="error", error=f"Profile '@{username}' does not exist!")
            self._add_message(f"❌ Profile not found!")
        except instaloader.exceptions.ConnectionException as e:
            self._update(status="error", error=f"Connection error: {str(e)[:100]}")
            self._add_message(f"❌ Connection error!")
        except Exception as e:
            self._update(status="error", error=str(e)[:200])
            self._add_message(f"❌ Error: {str(e)[:100]}")


def cleanup_old_tasks():
    """Remove tasks older than TTL."""
    now = datetime.now()
    with tasks_lock:
        expired = [
            tid for tid, t in tasks.items()
            if now - t.get("created", now) > timedelta(seconds=TASK_TTL_SECONDS)
        ]
        for tid in expired:
            task_dir = DOWNLOAD_DIR / tid
            if task_dir.exists():
                shutil.rmtree(task_dir, ignore_errors=True)
            del tasks[tid]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/download", methods=["POST"])
def start_download():
    """Start a new download task."""
    cleanup_old_tasks()

    data = request.get_json()
    raw_input = data.get("username", "").strip()

    if not raw_input:
        return jsonify({"error": "Please provide an Instagram username or URL"}), 400

    # Extract username from URL or input
    username = raw_input.replace("@", "")
    # Handle full URLs like instagram.com/username/reels
    if "instagram.com" in username:
        parts = username.split("instagram.com/")
        if len(parts) > 1:
            username = parts[1].split("/")[0].split("?")[0]

    username = username.strip("/").strip()
    if not username:
        return jsonify({"error": "Could not extract username"}), 400

    task_id = str(uuid.uuid4())[:8]

    with tasks_lock:
        tasks[task_id] = {
            "status": "starting",
            "progress": 0,
            "messages": [],
            "username": username,
            "total": 0,
            "downloaded": 0,
            "error": None,
            "zip_path": None,
            "created": datetime.now(),
        }

    # Start download in background thread
    def run():
        downloader = WebReelDownloader(task_id)
        downloader.download_reels(username)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    return jsonify({"task_id": task_id, "username": username})


@app.route("/progress/<task_id>")
def progress(task_id):
    """SSE endpoint for real-time progress."""
    def generate():
        last_msg_count = 0
        while True:
            with tasks_lock:
                task = tasks.get(task_id)
                if not task:
                    yield f"data: {json.dumps({'error': 'Task not found'})}\n\n"
                    return

                new_messages = task["messages"][last_msg_count:]
                last_msg_count = len(task["messages"])

                payload = {
                    "status": task["status"],
                    "progress": task["progress"],
                    "messages": new_messages,
                    "total": task.get("total", 0),
                    "downloaded": task.get("downloaded", 0),
                    "error": task.get("error"),
                    "zip_size": task.get("zip_size"),
                    "zip_filename": task.get("zip_filename"),
                }

            yield f"data: {json.dumps(payload)}\n\n"

            if task["status"] in ("done", "error"):
                return

            time.sleep(1)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/download/<task_id>")
def download_zip(task_id):
    """Serve the zip file for a completed task."""
    with tasks_lock:
        task = tasks.get(task_id)

    if not task or task["status"] != "done" or not task.get("zip_path"):
        return jsonify({"error": "Download not ready"}), 404

    zip_path = task["zip_path"]
    if not os.path.exists(zip_path):
        return jsonify({"error": "File expired, please re-download"}), 404

    return send_file(
        zip_path,
        mimetype="application/zip",
        as_attachment=True,
        download_name=task.get("zip_filename", "reels.zip"),
    )


if __name__ == "__main__":
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
