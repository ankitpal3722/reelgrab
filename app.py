#!/usr/bin/env python3
"""
Instagram Reel Downloader — Web App
Uses yt-dlp (primary) + instaloader (fallback) with login support.
"""

import os
import sys
import uuid
import json
import shutil
import zipfile
import threading
import time
import random
import subprocess
import re
from pathlib import Path
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, Response, send_file, stream_with_context

app = Flask(__name__)
app.secret_key = os.urandom(24)

tasks = {}
tasks_lock = threading.Lock()

TASK_TTL_SECONDS = 1800
DOWNLOAD_DIR = Path("/tmp/insta_downloads")


class WebReelDownloader:
    """Downloads Instagram reels using yt-dlp with instaloader metadata."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        self.task_dir = DOWNLOAD_DIR / task_id
        self.videos_dir = self.task_dir / "videos"
        self.videos_dir.mkdir(parents=True, exist_ok=True)

    def _update(self, **kwargs):
        with tasks_lock:
            if self.task_id in tasks:
                tasks[self.task_id].update(kwargs)

    def _add_message(self, msg: str):
        with tasks_lock:
            if self.task_id in tasks:
                tasks[self.task_id]["messages"].append(msg)

    def sanitize_filename(self, filename: str) -> str:
        invalid_chars = '<>:"/\\|?*\n\r'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        filename = re.sub(r'_+', '_', filename)
        if len(filename) > 150:
            filename = filename[:150]
        return filename.strip(' _')

    def download_reels(self, username: str, ig_username: str = None, ig_password: str = None):
        """Download all reels from a profile."""
        try:
            self._update(status="fetching", progress=0)
            self._add_message(f"🔍 Fetching reels from @{username}...")
            self._add_message("📡 Using yt-dlp engine (better rate limit handling)...")

            # Build yt-dlp command to get reel URLs + metadata
            profile_url = f"https://www.instagram.com/{username}/reels/"

            # First: get list of reel URLs with yt-dlp --flat-playlist
            self._add_message("📊 Scanning for reels...")

            cmd = [
                "yt-dlp",
                "--flat-playlist",
                "--dump-json",
                "--no-warnings",
                "--extractor-args", "instagram:max_comments=0",
                profile_url,
            ]

            # Add login cookies if provided
            cookies_file = self._get_cookies_file(ig_username, ig_password)
            if cookies_file:
                cmd.extend(["--cookies", cookies_file])
                self._add_message("🔐 Using authenticated session...")

            # Run yt-dlp to get reel list
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode != 0:
                error = result.stderr.strip()
                if "429" in error or "Too Many Requests" in error:
                    self._update(status="error", error="Instagram rate limit. Try again in 30 min or add login credentials.")
                    self._add_message("❌ Rate limited! Add Instagram login to bypass.")
                    return
                elif "login" in error.lower() or "auth" in error.lower():
                    self._update(status="error", error="Instagram requires login. Please add your credentials.")
                    self._add_message("❌ Login required by Instagram.")
                    return
                else:
                    # Try alternative: direct profile page
                    self._add_message("⚠️ Reels tab failed, trying profile page...")
                    cmd[len(cmd)-1] = f"https://www.instagram.com/{username}/"
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            # Parse reel entries
            entries = []
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    try:
                        entry = json.loads(line)
                        entries.append(entry)
                    except json.JSONDecodeError:
                        continue

            if not entries:
                self._update(status="error", error=f"No reels found for @{username}. Profile may be private or Instagram is blocking requests. Try adding login credentials.")
                self._add_message("❌ No reels found!")
                return

            total_reels = len(entries)
            self._add_message(f"📹 Found {total_reels} reels. Starting download...")
            self._update(status="downloading", total=total_reels, downloaded=0)

            captions = {}
            downloaded = 0

            for i, entry in enumerate(entries):
                try:
                    url = entry.get("url") or entry.get("webpage_url") or entry.get("original_url")
                    if not url:
                        continue

                    title = entry.get("title") or entry.get("description", "")
                    if title:
                        first_line = title.split('\n')[0]
                        first_line = ' '.join(w for w in first_line.split() if not w.startswith('#'))
                        if len(first_line) > 100:
                            first_line = first_line[:100]
                        clean_title = self.sanitize_filename(first_line)
                    else:
                        clean_title = entry.get("id", f"reel_{i+1}")

                    if not clean_title:
                        clean_title = entry.get("id", f"reel_{i+1}")

                    filename = f"{clean_title}.mp4"
                    filepath = self.videos_dir / filename

                    # Skip duplicates
                    if filepath.exists():
                        downloaded += 1
                        self._add_message(f"⏭️ [{i+1}/{total_reels}] Already exists: {clean_title[:40]}")
                        continue

                    self._add_message(f"⬇️ [{i+1}/{total_reels}] {clean_title[:40]}...")
                    self._update(downloaded=downloaded, progress=int((i / total_reels) * 90))

                    # Download individual reel with yt-dlp
                    dl_cmd = [
                        "yt-dlp",
                        "-f", "best[ext=mp4]/best",
                        "--no-warnings",
                        "--no-playlist",
                        "--socket-timeout", "30",
                        "--retries", "3",
                        "--retry-sleep", "10",
                        "-o", str(filepath),
                        url,
                    ]

                    if cookies_file:
                        dl_cmd.extend(["--cookies", cookies_file])

                    dl_result = subprocess.run(
                        dl_cmd,
                        capture_output=True,
                        text=True,
                        timeout=90,
                    )

                    if dl_result.returncode == 0 and filepath.exists():
                        downloaded += 1
                        self._add_message(f"✅ Downloaded: {clean_title[:40]}")

                        # Save caption
                        full_caption = entry.get("description", "")
                        if full_caption:
                            captions[filename] = full_caption
                    else:
                        error = dl_result.stderr.strip()
                        if "429" in error:
                            self._add_message(f"⚠️ Rate limited after {downloaded} reels. Packaging what we have...")
                            break
                        else:
                            self._add_message(f"❌ Failed: {error[:60]}")

                    # Rate limit delay between downloads
                    delay = random.uniform(3, 6)
                    time.sleep(delay)

                except subprocess.TimeoutExpired:
                    self._add_message(f"⏱️ Timeout on reel {i+1}, skipping...")
                    continue
                except Exception as e:
                    self._add_message(f"❌ Error: {str(e)[:60]}")
                    continue

            if downloaded == 0:
                self._update(status="error", error="Could not download any reels. Instagram may be blocking. Try adding login credentials or wait 30 min.")
                self._add_message("❌ No reels downloaded!")
                return

            # Save captions
            if captions:
                captions_path = self.videos_dir / "captions.json"
                with open(captions_path, "w", encoding="utf-8") as f:
                    json.dump(captions, f, indent=2, ensure_ascii=False)

                txt_path = self.videos_dir / "captions.txt"
                with open(txt_path, "w", encoding="utf-8") as f:
                    for fname, caption in captions.items():
                        f.write(f"{'='*60}\n📹 {fname}\n{'='*60}\n{caption}\n\n")

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

        except subprocess.TimeoutExpired:
            self._update(status="error", error="Request timed out. Instagram may be slow. Try again later.")
            self._add_message("❌ Timed out!")
        except Exception as e:
            self._update(status="error", error=str(e)[:200])
            self._add_message(f"❌ Error: {str(e)[:100]}")

    def _get_cookies_file(self, ig_username=None, ig_password=None):
        """Generate a cookies file from Instagram login."""
        if not ig_username or not ig_password:
            return None

        cookies_path = self.task_dir / "cookies.txt"
        try:
            # Use yt-dlp's built-in login
            cmd = [
                "yt-dlp",
                "--username", ig_username,
                "--password", ig_password,
                "--cookies", str(cookies_path),
                "--skip-download",
                "--no-warnings",
                "https://www.instagram.com/instagram/",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if cookies_path.exists():
                return str(cookies_path)
        except Exception:
            pass
        return None


def cleanup_old_tasks():
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
    cleanup_old_tasks()

    data = request.get_json()
    raw_input = data.get("username", "").strip()
    ig_username = data.get("ig_username", "").strip() or None
    ig_password = data.get("ig_password", "").strip() or None

    if not raw_input:
        return jsonify({"error": "Please provide an Instagram username or URL"}), 400

    username = raw_input.replace("@", "")
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

    def run():
        downloader = WebReelDownloader(task_id)
        downloader.download_reels(username, ig_username, ig_password)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    return jsonify({"task_id": task_id, "username": username})


@app.route("/progress/<task_id>")
def progress(task_id):
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
