# Instagram Reel Mass Downloader

Download all reels from any Instagram account with proper naming.

## Features

✅ Downloads all reels from an Instagram profile  
✅ Names files with reel titles (from captions)  
✅ Skips already downloaded videos  
✅ Rate limiting to avoid getting blocked  
✅ Progress tracking with emoji indicators  
✅ Clean filename sanitization  

## Installation

```bash
# Install required package
pip install instaloader
```

## Usage

### Basic Usage (Public Accounts)
```bash
python download_reels.py <instagram_username>
```

### Examples
```bash
# Download National Geographic reels
python download_reels.py natgeo

# Download reels from any public account
python download_reels.py cristiano
```

### Optional: Login for Better Access

If you want to download from private accounts you follow, edit the script and uncomment these lines:

```python
# Around line 190
downloader.login("your_username", "your_password")
```

## How It Works

1. **Fetches Profile**: Gets all posts from the Instagram account
2. **Filters Reels**: Only downloads video posts (reels)
3. **Smart Naming**: Uses the first line of the caption as the filename
4. **Sanitization**: Removes invalid characters and limits length
5. **Skip Duplicates**: Won't re-download existing files
6. **Rate Limiting**: Waits 2 seconds between downloads

## Output

All videos are saved in the `videos/` folder:

```
mass downloader insta/
├── download_reels.py
├── videos/
│   ├── Amazing sunset timelapse.mp4
│   ├── Behind the scenes.mp4
│   └── Travel vlog part 1.mp4
└── README.md
```

## Rate Limits

Instagram has rate limits. The script:
- Waits 2 seconds between downloads
- Recommends logging in for better access
- Shows clear progress to monitor activity

## Troubleshooting

### "Profile does not exist"
- Check the username spelling
- Make sure the account is public (or you're logged in)

### "Connection error"
- Check internet connection
- Instagram might be rate limiting you - wait 10-15 minutes

### Login Issues
- Use app-specific password if you have 2FA enabled
- Or download without login (public accounts only)

## Notes

- **Respect Privacy**: Only download content you have permission to use
- **Instagram Terms**: Be aware of Instagram's Terms of Service
- **Rate Limits**: Don't abuse the script - Instagram may temporarily block you
- **Storage**: Make sure you have enough disk space

## Advanced Options

To customize download behavior, edit the `InstaReelDownloader` initialization in the script:

```python
self.loader = instaloader.Instaloader(
    download_videos=True,          # Download videos
    download_video_thumbnails=False,  # Skip thumbnails
    download_comments=False,       # Skip comments
    save_metadata=False,          # Skip metadata files
    download_pictures=False,      # Skip images
)
```

## License

Free to use for personal projects. Respect Instagram's Terms of Service and content creator rights.
