# 🚀 Quick Start Guide

## Step 1: Install Dependencies
```bash
cd "mass downloader insta"
pip install -r requirements.txt
```

## Step 2: Run the Downloader

### Download from a public account:
```bash
python download_reels.py <username>
```

### Example - Download National Geographic reels:
```bash
python download_reels.py natgeo
```

### Example - Download Cristiano Ronaldo reels:
```bash
python download_reels.py cristiano
```

## What You'll See

```
============================================================
📸 Instagram Reel Mass Downloader
============================================================
✓ Output directory: /Users/.../videos

🔍 Fetching reels from @natgeo...
📱 Account: National Geographic (@natgeo)
👥 Followers: 283,456,789
📊 Posts: 24,567

⏬ Starting download...

⬇️  Downloading: Amazing wildlife moment.mp4
✅ Downloaded: Amazing wildlife moment.mp4

⬇️  Downloading: Ocean deep dive expedition.mp4
✅ Downloaded: Ocean deep dive expedition.mp4

============================================================
✨ Download Complete!
📥 Downloaded: 15 reels
⏭️  Skipped: 3 (already exist)
📁 Location: /Users/.../mass downloader insta/videos
============================================================
```

## All Videos Saved In:
```
mass downloader insta/videos/
```

## Tips

- **First run**: May take a while depending on how many reels exist
- **Subsequent runs**: Will skip already downloaded videos
- **Filenames**: Automatically cleaned and sanitized
- **Rate limiting**: Script waits 2 seconds between downloads

## Troubleshooting

**Username not found?**
- Remove the @ symbol, use just the username
- Make sure the account is public

**Connection errors?**
- Check internet connection
- Wait 10-15 minutes if rate limited
- Consider logging in (edit script)

Enjoy! 🎥
