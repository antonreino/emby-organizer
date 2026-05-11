# 🎬 Emby Organizer

Automated media library organization and management system for Emby media servers. This tool monitors a download directory, intelligently classifies and organizes media files (movies, TV series, and anime), and automatically syncs them to your Emby library with proper naming conventions and metadata enrichment.

## ✨ Features

- **Automatic Media Classification**: Intelligently distinguishes between movies, TV series, and anime based on filename patterns and metadata
- **Smart File Organization**: Automatically renames and organizes files according to Emby library standards
- **Metadata Enrichment**: Fetches metadata from TMDb (The Movie Database) for accurate information
- **Library Management**: Monitors downloads, detects stable files, and triggers Emby library refreshes
- **Remote Server Support**: SFTP/SSH support for remote Emby servers with configurable authentication
- **Telegram Notifications**: Real-time alerts for organization events and library updates
- **Systemd Integration**: Runs as a background service for continuous monitoring
- **Multi-Library Support**: Supports separate libraries for Anime, TV Series, and Movies

## 📋 Requirements

- Python 3.7+
- Emby Server
- (Optional) Remote SSH/SFTP server access
- (Optional) Telegram Bot for notifications
- (Optional) TMDb API key for metadata enrichment

## 🚀 Installation

### 1. Clone the repository

```bash
git clone https://github.com/antonreino/emby-organizer.git
cd emby-organizer
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

### Configuration Options

| Variable | Required | Description |
|----------|----------|-------------|
| `TMDB_API_KEY` | Optional | TMDb API key for metadata enrichment ([Get one here](https://www.themoviedb.org/settings/api)) |
| `TELEGRAM_BOT_TOKEN` | Optional | Telegram bot token for notifications |
| `TELEGRAM_CHAT_ID` | Optional | Telegram chat ID for notifications |
| `EMBY_API_KEY` | Yes | Emby server API key |
| `EMBY_URL` | Yes | Emby server URL (e.g., `http://127.0.0.1:8096`) |
| `INBOX_DIR` | Optional | Download directory (defaults to `/home/tone/Documentos/Torrent/Descargas`) |
| `EMBY_HOST` | Optional | SSH host for remote server (`user@host`) |
| `EMBY_PORT` | Optional | SSH port (default: 2222) |
| `EMBY_WATCH_DIR` | Optional | Remote watch directory path |
| `EMBY_SFTP_PASSWORD` | Optional | SSH password (leave empty for SSH key authentication) |
| `EMBY_SFTP_ANIME_URL`, `EMBY_SFTP_SERIES_URL`, `EMBY_SFTP_MOVIES_URL` | Optional | SFTP URLs for remote library destinations |

## 📖 Usage

### As a Script

```bash
python emby_organizer.py
```

The script will monitor the configured download directory and automatically organize new files.

### As a Systemd Service

Install the systemd service file:

```bash
sudo cp systemd/emby-organizer.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable emby-organizer.service
sudo systemctl start emby-organizer.service
```

Check service status:

```bash
sudo systemctl status emby-organizer.service
systemctl logs -u emby-organizer.service -f
```

### Refresh Emby Manually

```bash
curl -X POST "http://YOUR_EMBY_IP:8096/emby/Library/Refresh?api_key=YOUR_API_KEY"
```

### Watch Service (Monitors for New Files)

The project includes a watch service that monitors a remote Emby directory:

```bash
sudo cp systemd/emby-watch-refresh.service /etc/systemd/system/
sudo systemctl enable emby-watch-refresh.service
sudo systemctl start emby-watch-refresh.service
```

## 🎯 How It Works

1. **Continuous Monitoring**: Watches the configured inbox directory for new files
2. **Stability Detection**: Waits for files to be stable (no changes for 180 seconds) before processing
3. **Classification**: Analyzes filename and metadata to classify content
4. **Naming Convention**: Renames files according to Emby standards
   - Movies: `Movie Title (Year).mkv`
   - TV Series: `Series Name - S01E01 - Episode Title.mkv`
   - Anime: `Anime Title - 001 - Episode Title.mkv`
5. **Organization**: Moves files to appropriate library directories
6. **Metadata Fetch**: Queries TMDb for accurate information (if API key configured)
7. **Library Update**: Triggers Emby library refresh to index new content
8. **Notifications**: Sends Telegram notifications for processed content (if configured)

## 📊 Media Classification Logic

The organizer uses multiple heuristics to classify content:

- **Anime Detection**: Recognizes common anime markers (anime hints, release groups, naming patterns)
- **Series Detection**: Identifies episode patterns (S01E01, 1x01, "Cap 01")
- **Movie Detection**: Falls back to movie classification when series patterns aren't found

## 🔐 Security

- All sensitive data (API keys, passwords) are managed through environment variables
- The `.env` file is excluded from version control (see `.gitignore`)
- SSH key authentication is preferred over passwords for remote access
- No credentials are logged or exposed in output

## 📝 Logs

Logs are stored in:
```
~/.local/share/emby_organizer/organizer.log
```

## 🛠️ Project Structure

```
.
├── emby_organizer.py          # Main application
├── requirements.txt            # Python dependencies
├── README.md                   # This file
├── .env.example               # Configuration template
├── scripts/
│   ├── emby-watch-refresh.sh  # Watch and refresh script
│   ├── dashboard.sh           # Status dashboard
│   ├── logs.sh                # Log viewer
│   ├── status.sh              # Quick status check
│   └── ...
└── systemd/
    ├── emby-organizer.service      # Main service
    └── emby-watch-refresh.service  # Watch service
```

## 🤝 Contributing

Feel free to open issues and pull requests to improve this project.

## 📄 License

This project is open source and available under the MIT License.

## 🐛 Troubleshooting

### Files not being organized

- Check that `INBOX_DIR` is correctly configured
- Verify file permissions on the source directory
- Check logs: `~/.local/share/emby_organizer/organizer.log`

### Metadata not being fetched

- Ensure `TMDB_API_KEY` is set and valid
- Check internet connectivity
- TMDb might rate-limit requests during high load

### Emby library not updating

- Verify `EMBY_API_KEY` and `EMBY_URL` are correct
- Check Emby server is accessible at the configured URL
- Ensure the API key has appropriate permissions

### Remote SFTP issues

- Verify SSH credentials and key permissions (`chmod 600`)
- Test connection manually: `ssh -p PORT user@host`
- Check `EMBY_WATCH_DIR` path exists on remote server

## 📞 Support

For issues and questions, please open an issue on the GitHub repository.
