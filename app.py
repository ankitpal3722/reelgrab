#!/usr/bin/env python3
"""
Instagram Reel Downloader — Web App
Uses RapidAPI Instagram Scraper for reliable cloud-based downloading.
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
import re
import requests as http_requests
from pathlib import Path
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, Response, send_file, stream_with_context

app = Flask(__name__)
app.secret_key = os.urandom(24)

tasks = {}
tasks_lock = threading.Lock()

TASK_TTL_SECONDS = 1800
DOWNLOAD_DIR = Path("/tmp/insta_downloads")

# RapidAPI configuration
RAPIDAPI_KEY = os.environ.get("RAPIDAPI_KEY", "")

# API endpoints (Instagram Scraper API2)
RAPIDAPI_HOST = "instagram-scraper-api2.p.rapidapi.com"
RAPIDAPI_BASE = f"https://{RAPIDAPI_HOST}/v1"


class WebReelDownloader:
    """Downloads Instagram reels using RapidAPI Instagram Scraper."""

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

    def _api_request(self, endpoint: str, params: dict = None):
        """Make a request to the RapidAPI Instagram Scraper."""
        headers = {
            "x-rapidapi-key": RAPIDAPI_KEY,
            "x-rapidapi-host": RAPIDAPI_HOST,
        }
        url = f"{RAPIDAPI_BASE}/{endpoint}"
        resp = http_requests.get(url, headers=headers, params=params or {}, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def download_reels(self, username: str, ig_username: str = None, ig_password: str = None):
        """Download all reels from a profile using RapidAPI."""
        try:
            if not RAPIDAPI_KEY:
                self._update(
                    status="error",
                    error="RapidAPI key not configured. Set RAPIDAPI_KEY environment variable on Render.",
                )
                self._add_message("❌ No API key! Add RAPIDAPI_KEY in Render settings.")
                return

            self._update(status="fetching", progress=5)
            self._add_message(f"🔍 Fetching reels from @{username}...")
            self._add_message("📡 Using RapidAPI Instagram Scraper (no IP blocking)...")

            # Step 1: Get user info to get user_id
            self._add_message("👤 Looking up profile...")
            try:
                info_data = self._api_request("info", {"username_or_id_or_url": username})
            except http_requests.exceptions.HTTPError as e:
                if e.response.status_code == 404:
                    self._update(status="error", error=f"Profile @{username} not found.")
                    self._add_message(f"❌ @{username} not found!")
                    return
                elif e.response.status_code == 429:
                    self._update(status="error", error="API rate limit reached. Try again in a few minutes.")
                    self._add_message("❌ API rate limit. Wait a minute and retry.")
                    return
                elif e.response.status_code == 403:
                    self._update(status="error", error="Invalid API key. Check RAPIDAPI_KEY env variable.")
                    self._add_message("❌ Invalid API key!")
                    return
                raise

            user_data = info_data.get("data", {})
            user_id = user_data.get("id")
            full_name = user_data.get("full_name", username)
            is_private = user_data.get("is_private", False)

            if is_private:
                self._update(status="error", error=f"@{username} is a private account. Reels cannot be downloaded.")
                self._add_message(f"🔒 @{username} is private!")
                return

            self._add_message(f"✅ Found: {full_name} (@{username})")

            # Step 2: Fetch reels
            self._add_message("📊 Scanning reels...")
            self._update(status="scanning", progress=15)

            all_reels = []
            pagination_token = None
            page = 0

            while True:
                page += 1
                params = {"username_or_id_or_url": username}
                if pagination_token:
                    params["pagination_token"] = pagination_token

                try:
                    reels_data = self._api_request("reels", params)
                except http_requests.exceptions.HTTPError as e:
                    if e.response.status_code == 429:
                        self._add_message(f"⚠️ Rate limited after finding {len(all_reels)} reels. Downloading what we have...")
                        break
                    raise

                items = reels_data.get("data", {}).get("items", [])
                if not items:
                    break

                all_reels.extend(items)
                self._add_message(f"📹 Found {len(all_reels)} reels so far... (page {page})")

                pagination_token = reels_data.get("pagination_token")
                if not pagination_token:
                    break

                # Small delay between pagination requests
                time.sleep(1)

            if not all_reels:
                self._update(status="error", error=f"No reels found for @{username}.")
                self._add_message("❌ No reels found!")
                return

            total_reels = len(all_reels)
            self._add_message(f"📹 Total: {total_reels} reels. Starting download...")
            self._update(status="downloading", total=total_reels, downloaded=0, progress=20)

            captions = {}
            downloaded = 0

            for i, reel in enumerate(all_reels):
                try:
                    # Extract video URL from reel data
                    video_url = None

                    # Try different possible structures
                    video_versions = reel.get("video_versions", [])
                    if video_versions:
                        # Get highest quality
                        video_url = video_versions[0].get("url")
                    elif reel.get("video_url"):
                        video_url = reel["video_url"]

                    if not video_url:
                        # Try nested structure
                        media = reel.get("media", {})
                        video_versions = media.get("video_versions", [])
                        if video_versions:
                            video_url = video_versions[0].get("url")

                    if not video_url:
                        self._add_message(f"⏭️ [{i+1}/{total_reels}] No video URL, skipping...")
                        continue

                    # Get caption
                    caption_data = reel.get("caption", {})
                    if isinstance(caption_data, dict):
                        caption_text = caption_data.get("text", "")
                    elif isinstance(caption_data, str):
                        caption_text = caption_data
                    else:
                        caption_text = ""

                    # Create filename
                    if caption_text:
                        first_line = caption_text.split('\n')[0]
                        first_line = ' '.join(w for w in first_line.split() if not w.startswith('#'))
                        if len(first_line) > 80:
                            first_line = first_line[:80]
                        clean_title = self.sanitize_filename(first_line)
                    else:
                        clean_title = ""

                    reel_id = reel.get("code") or reel.get("pk") or reel.get("id", f"reel_{i+1}")
                    if not clean_title:
                        clean_title = str(reel_id)

                    filename = f"{clean_title}.mp4"
                    filepath = self.videos_dir / filename

                    # Skip duplicates
                    if filepath.exists():
                        downloaded += 1
                        self._add_message(f"⏭️ [{i+1}/{total_reels}] Already exists: {clean_title[:40]}")
                        continue

                    self._add_message(f"⬇️ [{i+1}/{total_reels}] {clean_title[:40]}...")
                    progress = 20 + int((i / total_reels) * 70)
                    self._update(downloaded=downloaded, progress=progress)

                    # Download video directly from Instagram CDN
                    try:
                        vid_resp = http_requests.get(
                            video_url,
                            stream=True,
                            timeout=60,
                            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                        )
                        vid_resp.raise_for_status()

                        with open(filepath, "wb") as f:
                            for chunk in vid_resp.iter_content(chunk_size=8192):
                                f.write(chunk)

                        if filepath.exists() and filepath.stat().st_size > 1000:
                            downloaded += 1
                            self._add_message(f"✅ Downloaded: {clean_title[:40]}")

                            # Save caption
                            if caption_text:
                                captions[filename] = caption_text
                        else:
                            filepath.unlink(missing_ok=True)
                            self._add_message(f"❌ [{i+1}] File too small, skipped")

                    except http_requests.exceptions.RequestException as e:
                        self._add_message(f"❌ [{i+1}] Download failed: {str(e)[:50]}")
                        continue

                    # Small delay between downloads
                    time.sleep(random.uniform(0.5, 1.5))

                except Exception as e:
                    self._add_message(f"❌ Error on reel {i+1}: {str(e)[:60]}")
                    continue

            if downloaded == 0:
                self._update(status="error", error="Could not download any reels. Video URLs may have expired. Try again.")
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

        except http_requests.exceptions.RequestException as e:
            self._update(status="error", error=f"API error: {str(e)[:150]}")
            self._add_message(f"❌ API error: {str(e)[:100]}")
        except Exception as e:
            self._update(status="error", error=str(e)[:200])
            self._add_message(f"❌ Error: {str(e)[:100]}")


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

    if not RAPIDAPI_KEY:
        return jsonify({"error": "Server missing API key. Admin needs to set RAPIDAPI_KEY."}), 500

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
        downloader.download_reels(username)

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
