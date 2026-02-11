"""
Instagram Reel Mass Downloader
Downloads all reels from an Instagram account and saves them with their titles.

Usage:
    python download_reels.py <instagram_username>
    
Example:
    python download_reels.py natgeo
"""

import instaloader
import os
import sys
from pathlib import Path
import time
from typing import Optional

class InstaReelDownloader:
    def __init__(self, output_dir: str = "videos"):
        """
        Initialize the Instagram Reel Downloader
        
        Args:
            output_dir: Directory to save downloaded videos (default: 'videos')
        """
        self.loader = instaloader.Instaloader(
            download_videos=True,
            download_video_thumbnails=False,
            download_comments=False,
            save_metadata=False,
            compress_json=False,
            download_pictures=False,
            download_geotags=False,
        )
        
        # Create output directory
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        print(f"✓ Output directory: {self.output_dir.absolute()}")
    
    def login(self, username: Optional[str] = None, password: Optional[str] = None):
        """
        Login to Instagram (optional, but recommended for better access)
        
        Args:
            username: Instagram username
            password: Instagram password
        """
        if username and password:
            try:
                self.loader.login(username, password)
                print(f"✓ Logged in as {username}")
                return True
            except Exception as e:
                print(f"⚠ Login failed: {e}")
                print("Continuing without login (public reels only)...")
                return False
        return False
    
    def sanitize_filename(self, filename: str) -> str:
        """
        Sanitize filename by removing invalid characters
        
        Args:
            filename: Original filename
            
        Returns:
            Sanitized filename safe for filesystem
        """
        # Remove or replace invalid characters
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        
        # Limit length
        if len(filename) > 200:
            filename = filename[:200]
        
        return filename.strip()
    
    def download_reels(self, username: str):
        """
        Download all reels from an Instagram account
        
        Args:
            username: Instagram username/handle (without @)
        """
        try:
            print(f"\n🔍 Fetching reels from @{username}...")
            
            # Get profile
            profile = instaloader.Profile.from_username(self.loader.context, username)
            
            print(f"📱 Account: {profile.full_name} (@{profile.username})")
            print(f"👥 Followers: {profile.followers:,}")
            print(f"📊 Posts: {profile.mediacount:,}")
            
            # Counter for downloaded reels
            reel_count = 0
            skipped_count = 0
            
            print(f"\n⏬ Starting download...\n")
            
            # Iterate through all posts
            for post in profile.get_posts():
                # Check if it's a reel (video)
                if post.is_video and post.typename == 'GraphVideo':
                    try:
                        # Get reel title/caption (first line or use shortcode)
                        if post.caption:
                            # Use first line of caption as title
                            title = post.caption.split('\n')[0]
                            # Remove hashtags from title
                            title = ' '.join(word for word in title.split() if not word.startswith('#'))
                            # Limit title length
                            if len(title) > 100:
                                title = title[:100]
                        else:
                            title = post.shortcode
                        
                        # Clean the title for filename
                        clean_title = self.sanitize_filename(title)
                        if not clean_title:
                            clean_title = post.shortcode
                        
                        # Create filename
                        filename = f"{clean_title}.mp4"
                        filepath = self.output_dir / filename
                        
                        # Skip if already downloaded
                        if filepath.exists():
                            print(f"⏭️  Skipped (exists): {filename}")
                            skipped_count += 1
                            continue
                        
                        # Download the reel
                        print(f"⬇️  Downloading: {filename}")
                        
                        # Download video
                        self.loader.download_post(post, target=str(self.output_dir))
                        
                        # Instaloader creates files with specific naming, rename them
                        # Find the downloaded file
                        downloaded_files = list(self.output_dir.glob(f"{post.date_utc.strftime('%Y-%m-%d_%H-%M-%S')}_UTC*.mp4"))
                        if not downloaded_files:
                            # Try alternative pattern
                            downloaded_files = list(self.output_dir.glob(f"*{post.shortcode}*.mp4"))
                        
                        if downloaded_files:
                            # Rename to our desired filename
                            downloaded_files[0].rename(filepath)
                            
                            # Clean up any extra files (json, txt, etc.)
                            for ext in ['txt', 'json', 'xz']:
                                for extra_file in self.output_dir.glob(f"{post.date_utc.strftime('%Y-%m-%d_%H-%M-%S')}_UTC*.{ext}"):
                                    extra_file.unlink()
                                for extra_file in self.output_dir.glob(f"*{post.shortcode}*.{ext}"):
                                    extra_file.unlink()
                        
                        reel_count += 1
                        print(f"✅ Downloaded: {filename}\n")
                        
                        # Rate limiting - be nice to Instagram
                        time.sleep(2)
                        
                    except Exception as e:
                        print(f"❌ Error downloading reel: {e}\n")
                        continue
            
            print(f"\n{'='*60}")
            print(f"✨ Download Complete!")
            print(f"📥 Downloaded: {reel_count} reels")
            print(f"⏭️  Skipped: {skipped_count} (already exist)")
            print(f"📁 Location: {self.output_dir.absolute()}")
            print(f"{'='*60}\n")
            
        except instaloader.exceptions.ProfileNotExistsException:
            print(f"❌ Error: Profile '@{username}' does not exist!")
            sys.exit(1)
        except instaloader.exceptions.ConnectionException as e:
            print(f"❌ Connection error: {e}")
            print("Try again later or check your internet connection.")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Unexpected error: {e}")
            sys.exit(1)


def main():
    """Main entry point"""
    print("="*60)
    print("📸 Instagram Reel Mass Downloader")
    print("="*60)
    
    # Check command line arguments
    if len(sys.argv) < 2:
        print("\n❌ Error: No username provided!")
        print("\nUsage:")
        print(f"  python {sys.argv[0]} <instagram_username>")
        print("\nExample:")
        print(f"  python {sys.argv[0]} natgeo")
        print()
        sys.exit(1)
    
    username = sys.argv[1].replace('@', '').strip()
    
    if not username:
        print("❌ Error: Invalid username!")
        sys.exit(1)
    
    # Initialize downloader
    downloader = InstaReelDownloader(output_dir="videos")
    
    # Optional: Login for better access (uncomment and provide credentials)
    # downloader.login("your_username", "your_password")
    
    # Download reels
    downloader.download_reels(username)


if __name__ == "__main__":
    main()
