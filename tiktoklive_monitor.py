import asyncio
import csv
import json
import os
import signal
import sys
import argparse
import platform
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
import logging
from pathlib import Path

from TikTokLive.client.client import TikTokLiveClient
from TikTokLive.client.logger import LogLevel
from TikTokLive.events import ConnectEvent, DisconnectEvent, CommentEvent, GiftEvent
from TikTokLive.events.custom_events import FollowEvent, ShareEvent
from TikTokLive.events.proto_events import JoinEvent

class StreamMonitor:
    """Monitor multiple TikTok streamers and auto-record when they go live"""

    def __init__(self, config_file: str = "streamers_config.json", session_id: Optional[str] = None):
        self.config_file = config_file
        self.global_session_id = session_id  # Command line session ID takes precedence
        self.config = self.load_config()  # Load config first
        self.config_last_modified = self.get_config_mtime()  # Track file modification time
        self.active_recordings: Dict[str, TikTokLiveClient] = {}
        self.monitoring = True
        self.is_windows = platform.system() == "Windows"

        # Use Path for cross-platform compatibility
        self.session_log_file = Path(f"monitoring_sessions_{datetime.now().strftime('%Y%m%d')}.csv")

        # File-based termination signals
        self.stop_file = Path("stop_monitor.txt")
        self.pause_file = Path("pause_monitor.txt")
        self.status_file = Path("monitor_status.txt")

        # Override config session_id if provided via command line (after config is loaded)
        if self.global_session_id:
            self.config['settings']['session_id'] = self.global_session_id

        # Set up logging with filtered levels
        log_file = Path(f"monitor_{datetime.now().strftime('%Y%m%d')}.log")
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

        # Silence verbose HTTP logs from TikTokLive and httpx
        logging.getLogger("TikTokLive").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("requests").setLevel(logging.WARNING)

        # Only show our monitor logs at INFO level
        self.logger.setLevel(logging.INFO)

        # Log session ID usage
        if self.global_session_id:
            self.logger.info(f"🔑 Using session ID from command line argument")
        elif self.config['settings'].get('session_id'):
            self.logger.info(f"🔑 Using session ID from config file")
        else:
            self.logger.info("ℹ️  No session ID provided - only public streams accessible")

        # Ensure environment variable is always set when using session IDs
        if self.config['settings'].get('session_id'):
            whitelist_host = self.config['settings'].get('whitelist_sign_server', 'tiktok.eulerstream.com')
            os.environ['WHITELIST_AUTHENTICATED_SESSION_ID_HOST'] = whitelist_host
            self.logger.info(f"🔐 Sign server whitelisted: {whitelist_host}")

        # Initialize session log
        self.init_session_log()

        # Set up signal handlers for graceful shutdown (Windows compatible)
        self.setup_signal_handlers()

        # Clean up any existing control files
        self.cleanup_control_files()

        # Create initial status file
        self.update_status_file("starting")

    def setup_signal_handlers(self):
        """Set up signal handlers compatible with Windows"""
        try:
            if self.is_windows:
                # Windows supports limited signals
                signal.signal(signal.SIGINT, self.signal_handler)
                signal.signal(signal.SIGTERM, self.signal_handler)
                # SIGBREAK is Windows-specific
                if hasattr(signal, 'SIGBREAK'):
                    signal.signal(signal.SIGBREAK, self.signal_handler)
            else:
                # Unix-like systems support more signals
                signal.signal(signal.SIGINT, self.signal_handler)
                signal.signal(signal.SIGTERM, self.signal_handler)
                signal.signal(signal.SIGHUP, self.signal_handler)
        except Exception as e:
            self.logger.warning(f"Could not set up all signal handlers: {e}")

    def cleanup_control_files(self):
        """Remove any existing control files from previous runs"""
        for file_path in [self.stop_file, self.pause_file]:
            if file_path.exists():
                try:
                    file_path.unlink()
                    self.logger.debug(f"Removed existing control file: {file_path}")
                except Exception as e:
                    self.logger.warning(f"Could not remove {file_path}: {e}")

    def update_status_file(self, status: str, extra_info: str = ""):
        """Update the status file with current monitoring state"""
        try:
            status_info = {
                "timestamp": datetime.now().isoformat(),
                "status": status,
                "active_recordings": len(self.active_recordings),
                "currently_recording": list(self.active_recordings.keys()),
                "extra_info": extra_info,
                "pid": os.getpid(),
                "platform": platform.system()
            }

            with open(self.status_file, 'w', encoding='utf-8') as f:
                json.dump(status_info, f, indent=2, ensure_ascii=False)

        except Exception as e:
            self.logger.debug(f"Could not update status file: {e}")

    def check_control_signals(self) -> str:
        """Check for file-based control signals"""
        # Check for stop signal
        if self.stop_file.exists():
            try:
                with open(self.stop_file, 'r', encoding='utf-8') as f:
                    reason = f.read().strip() or "file_signal"
                return f"stop:{reason}"
            except Exception:
                return "stop:file_signal"

        # Check for pause signal
        if self.pause_file.exists():
            try:
                with open(self.pause_file, 'r', encoding='utf-8') as f:
                    duration = f.read().strip()
                    if duration.isdigit():
                        return f"pause:{duration}"
                    return "pause:60"  # Default 60 seconds
            except Exception:
                return "pause:60"

        return "continue"

    def get_config_mtime(self) -> float:
        """Get the modification time of the config file"""
        try:
            config_path = Path(self.config_file)
            if config_path.exists():
                return config_path.stat().st_mtime
            return 0.0
        except Exception:
            return 0.0

    def check_config_changes(self) -> bool:
        """Check if the config file has been modified and reload if needed"""
        try:
            current_mtime = self.get_config_mtime()
            if current_mtime > self.config_last_modified:
                self.logger.info("📝 Config file changed, reloading...")

                # Store old config for comparison
                old_streamers = set(self.config.get('streamers', {}).keys())
                old_enabled = {k: v.get('enabled', True) for k, v in self.config.get('streamers', {}).items()}

                # Reload config
                new_config = self.load_config()

                # Preserve command line session ID override
                if self.global_session_id:
                    new_config['settings']['session_id'] = self.global_session_id

                self.config = new_config
                self.config_last_modified = current_mtime

                # Compare changes
                new_streamers = set(self.config.get('streamers', {}).keys())
                new_enabled = {k: v.get('enabled', True) for k, v in self.config.get('streamers', {}).items()}

                # Log changes
                added = new_streamers - old_streamers
                removed = old_streamers - new_streamers
                status_changed = []

                for streamer in old_streamers & new_streamers:
                    old_status = old_enabled.get(streamer, True)
                    new_status = new_enabled.get(streamer, True)
                    if old_status != new_status:
                        status = "enabled" if new_status else "disabled"
                        status_changed.append(f"{streamer}({status})")

                if added:
                    self.logger.info(f"➕ Added streamers: {', '.join(added)}")
                if removed:
                    self.logger.info(f"➖ Removed streamers: {', '.join(removed)}")
                    # Stop any active recordings for removed streamers
                    for streamer_key in removed:
                        username = f"@{streamer_key}"  # Assuming format
                        if username in self.active_recordings:
                            asyncio.create_task(self.stop_recording(username, "removed_from_config"))
                if status_changed:
                    self.logger.info(f"🔄 Status changed: {', '.join(status_changed)}")

                total_enabled = len([s for s in self.config['streamers'].values() if s.get('enabled', True)])
                self.logger.info(f"📋 Now monitoring {total_enabled} streamers")

                return True

        except Exception as e:
            self.logger.error(f"Error checking config changes: {e}")

        return False

    def load_config(self) -> dict:
        """Load or create configuration file"""
        default_config = {
            "streamers": {
                "example_user1": {
                    "username": "@example_user1",
                    "enabled": True,
                    "session_id": None,
                    "tt_target_idc": None,
                    "tags": ["research", "category1"],
                    "notes": "Example streamer for research"
                },
                "example_user2": {
                    "username": "@example_user2",
                    "enabled": True,
                    "session_id": None,
                    "tt_target_idc": None,
                    "tags": ["research", "category2"],
                    "notes": "Another example streamer"
                }
            },
            "settings": {
                "check_interval_seconds": 30,
                "max_concurrent_recordings": 3,
                "output_directory": "recordings",
                "session_id": None,
                "tt_target_idc": "us-eastred",
                "whitelist_sign_server": "tiktok.eulerstream.com"
            }
        }

        config_path = Path(self.config_file)
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.error(f"Error loading config: {e}")
                return default_config
        else:
            # Create default config file
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=2, ensure_ascii=False)
            self.logger.info(f"Created default config file: {config_path}")
            return default_config

    def init_session_log(self):
        """Initialize the session monitoring log CSV"""
        if not self.session_log_file.exists():
            with open(self.session_log_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp', 'username', 'action', 'status', 'duration_minutes',
                    'comments_count', 'gifts_count', 'follows_count', 'shares_count',
                    'joins_count', 'tags', 'notes', 'error_message'
                ])

    def log_session_event(self, username: str, action: str, status: str = 'success',
                         duration_minutes: float = 0, stats: dict = None,
                         error_message: str = ''):
        """Log monitoring events to CSV"""
        stats = stats or {}
        streamer_config = self.config['streamers'].get(username.replace('@', ''), {})

        with open(self.session_log_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                datetime.now().isoformat(),
                username,
                action,
                status,
                round(duration_minutes, 2),
                stats.get('comments', 0),
                stats.get('gifts', 0),
                stats.get('follows', 0),
                stats.get('shares', 0),
                stats.get('joins', 0),
                ';'.join(streamer_config.get('tags', [])),
                streamer_config.get('notes', ''),
                error_message
            ])

    async def check_streamer_status(self, username: str) -> bool:
        """Check if a streamer is currently live"""
        try:
            # Ensure environment variable is set for authenticated sessions
            whitelist_host = self.config['settings'].get('whitelist_sign_server', 'tiktok.eulerstream.com')
            os.environ['WHITELIST_AUTHENTICATED_SESSION_ID_HOST'] = whitelist_host

            client = TikTokLiveClient(unique_id=username)

            # Set session ID if available
            streamer_config = self.config['streamers'].get(username.replace('@', ''), {})
            session_id = streamer_config.get('session_id') or self.config['settings'].get('session_id')
            tt_target_idc = streamer_config.get('tt_target_idc') or self.config['settings'].get('tt_target_idc')

            if session_id:
                client.web.set_session(session_id, tt_target_idc)

            # Add timeout to prevent hanging
            is_live = await asyncio.wait_for(client.is_live(), timeout=10.0)
            return is_live

        except asyncio.TimeoutError:
            self.logger.debug(f"Timeout checking {username}")
            return False
        except Exception as e:
            self.logger.debug(f"Error checking {username}: {e}")
            return False

    async def check_all_streamers_parallel(self, enabled_streamers: dict) -> dict:
        """Check all streamers in parallel and return their live status"""
        async def check_single_streamer(streamer_key: str, streamer_config: dict):
            username = streamer_config['username']
            try:
                is_live = await self.check_streamer_status(username)
                return username, is_live
            except Exception as e:
                self.logger.debug(f"Error in parallel check for {username}: {e}")
                return username, False

        # Create tasks for all streamers
        tasks = [
            check_single_streamer(streamer_key, streamer_config)
            for streamer_key, streamer_config in enabled_streamers.items()
        ]

        # Run all checks in parallel with a reasonable timeout
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=30.0  # Max 30 seconds for all checks
            )

            # Process results
            live_status = {}
            for result in results:
                if isinstance(result, tuple):
                    username, is_live = result
                    live_status[username] = is_live
                else:
                    # Handle exceptions
                    self.logger.debug(f"Exception in parallel check: {result}")

            return live_status

        except asyncio.TimeoutError:
            self.logger.warning("⚠️  Parallel streamer check timed out - some checks may be incomplete")
            return {config['username']: False for config in enabled_streamers.values()}

    async def start_recording(self, username: str):
        """Start recording a streamer"""
        if username in self.active_recordings:
            self.logger.warning(f"Already recording {username}")
            return

        if len(self.active_recordings) >= self.config['settings']['max_concurrent_recordings']:
            self.logger.warning(f"Max concurrent recordings reached. Skipping {username}")
            self.log_session_event(username, 'recording_attempt', 'failed',
                                 error_message='Max concurrent recordings reached')
            return

        try:
            self.logger.info(f"🔴 Starting recording for {username}")

            # Ensure environment variable is set for authenticated sessions
            whitelist_host = self.config['settings'].get('whitelist_sign_server', 'tiktok.eulerstream.com')
            os.environ['WHITELIST_AUTHENTICATED_SESSION_ID_HOST'] = whitelist_host
            self.logger.debug(f"🔐 Environment variable set: WHITELIST_AUTHENTICATED_SESSION_ID_HOST={whitelist_host}")

            # Create client
            client = TikTokLiveClient(unique_id=username)

            # Set session ID if available
            streamer_config = self.config['streamers'].get(username.replace('@', ''), {})
            session_id = streamer_config.get('session_id') or self.config['settings'].get('session_id')
            tt_target_idc = streamer_config.get('tt_target_idc') or self.config['settings'].get('tt_target_idc')

            if session_id:
                client.web.set_session(session_id, tt_target_idc)
                self.logger.debug(f"🔑 Session ID configured for {username}")

            # Set up file paths using Path for cross-platform compatibility
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            username_clean = username.replace("@", "")
            output_dir = Path(self.config['settings']['output_directory'])
            output_dir.mkdir(parents=True, exist_ok=True)

            # Create CSV files
            csv_files = {
                'comments': output_dir / f"{username_clean}_{timestamp}_comments.csv",
                'gifts': output_dir / f"{username_clean}_{timestamp}_gifts.csv",
                'follows': output_dir / f"{username_clean}_{timestamp}_follows.csv",
                'shares': output_dir / f"{username_clean}_{timestamp}_shares.csv",
                'joins': output_dir / f"{username_clean}_{timestamp}_joins.csv"
            }

            # Initialize CSV files and keep file handles open
            csv_writers = self.init_csv_files_with_handles(csv_files)

            # Store recording info
            recording_info = {
                'client': client,
                'start_time': datetime.now(),
                'csv_files': csv_files,
                'csv_writers': csv_writers,  # Keep file handles and writers
                'stats': {'comments': 0, 'gifts': 0, 'follows': 0, 'shares': 0, 'joins': 0},
                'is_recording': True  # Flag to track recording state
            }

            # Set up event handlers
            self.setup_event_handlers(client, username, recording_info)

            # Start the client
            await client.start(fetch_room_info=True)
            self.active_recordings[username] = recording_info

            self.log_session_event(username, 'recording_started', 'success')
            self.logger.info(f"✅ Successfully started recording {username}")

        except Exception as e:
            self.logger.error(f"❌ Failed to start recording {username}: {e}")
            self.log_session_event(username, 'recording_started', 'failed',
                                 error_message=str(e))

    def init_csv_files_with_handles(self, csv_files: dict) -> dict:
        """Initialize CSV files with headers and return open file handles with writers"""
        headers = {
            'comments': ['timestamp', 'user_id', 'nickname', 'comment', 'follower_count'],
            'gifts': ['timestamp', 'user_id', 'nickname', 'gift_name', 'repeat_count', 'streakable', 'streaking'],
            'follows': ['timestamp', 'user_id', 'nickname', 'follow_count', 'share_type', 'action'],
            'shares': ['timestamp', 'user_id', 'nickname', 'share_type', 'share_target', 'share_count', 'users_joined', 'action'],
            'joins': ['timestamp', 'user_id', 'nickname', 'count', 'is_top_user', 'enter_type', 'action', 'user_share_type', 'client_enter_source']
        }

        csv_writers = {}
        for csv_type, filepath in csv_files.items():
            # Open file and create writer
            file_handle = open(filepath, 'w', newline='', encoding='utf-8')
            writer = csv.writer(file_handle)
            writer.writerow(headers[csv_type])

            # Store both file handle and writer for proper cleanup
            csv_writers[csv_type] = {
                'file_handle': file_handle,
                'writer': writer
            }

        return csv_writers

    def setup_event_handlers(self, client: TikTokLiveClient, username: str, recording_info: dict):
        """Set up event handlers for the client"""

        @client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            self.logger.info(f"📡 Connected to {username}'s stream (Room: {client.room_id})")

            # Start video recording with error handling
            timestamp = recording_info['start_time'].strftime("%Y%m%d_%H%M%S")
            username_clean = username.replace("@", "")
            output_dir = Path(self.config['settings']['output_directory'])
            video_file = output_dir / f"{username_clean}_{timestamp}.mp4"

            try:
                # Ensure the video recording starts properly
                if hasattr(client.web, 'fetch_video_data'):
                    client.web.fetch_video_data.start(
                        output_fp=str(video_file),  # Convert Path to string for compatibility
                        room_info=client.room_info,
                        output_format="mp4"
                    )
                    recording_info['video_file'] = video_file
                    self.logger.info(f"🎥 Started video recording: {video_file}")
                else:
                    self.logger.warning(f"⚠️  Video recording not available for {username}")
            except Exception as e:
                self.logger.error(f"Failed to start video recording for {username}: {e}")

        @client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent):
            await self.stop_recording(username, "stream_ended")

        @client.on(CommentEvent)
        async def on_comment(event: CommentEvent):
            # Check if recording is still active
            if not recording_info.get('is_recording', False):
                return

            timestamp_now = datetime.now().isoformat()
            recording_info['stats']['comments'] += 1

            try:
                writer = recording_info['csv_writers']['comments']['writer']
                writer.writerow([
                    timestamp_now,
                    getattr(event.user, 'unique_id', ''),
                    getattr(event.user, 'nickname', ''),
                    event.comment,
                    getattr(event.user, 'follower_count', 0)
                ])
                # Flush to ensure data is written immediately
                recording_info['csv_writers']['comments']['file_handle'].flush()
            except Exception as e:
                if recording_info.get('is_recording', False):  # Only log if we should still be recording
                    self.logger.error(f"Error writing comment event: {e}")

        @client.on(GiftEvent)
        async def on_gift(event: GiftEvent):
            # Check if recording is still active
            if not recording_info.get('is_recording', False):
                return

            timestamp_now = datetime.now().isoformat()
            recording_info['stats']['gifts'] += 1

            try:
                writer = recording_info['csv_writers']['gifts']['writer']
                writer.writerow([
                    timestamp_now,
                    getattr(event.user, 'unique_id', ''),
                    getattr(event.user, 'nickname', ''),
                    event.gift.name,
                    event.repeat_count,
                    event.gift.streakable,
                    event.streaking
                ])
                recording_info['csv_writers']['gifts']['file_handle'].flush()
            except Exception as e:
                if recording_info.get('is_recording', False):  # Only log if we should still be recording
                    self.logger.error(f"Error writing gift event: {e}")

        @client.on(FollowEvent)
        async def on_follow(event: FollowEvent):
            # Check if recording is still active
            if not recording_info.get('is_recording', False):
                return

            timestamp_now = datetime.now().isoformat()
            recording_info['stats']['follows'] += 1

            try:
                writer = recording_info['csv_writers']['follows']['writer']
                writer.writerow([
                    timestamp_now,
                    getattr(event.user, 'unique_id', ''),
                    getattr(event.user, 'nickname', ''),
                    getattr(event, 'follow_count', 0),
                    getattr(event, 'share_type', 0),
                    getattr(event, 'action', 0)
                ])
                recording_info['csv_writers']['follows']['file_handle'].flush()
            except Exception as e:
                if recording_info.get('is_recording', False):  # Only log if we should still be recording
                    self.logger.error(f"Error writing follow event: {e}")

        @client.on(ShareEvent)
        async def on_share(event: ShareEvent):
            # Check if recording is still active
            if not recording_info.get('is_recording', False):
                return

            timestamp_now = datetime.now().isoformat()
            recording_info['stats']['shares'] += 1

            try:
                writer = recording_info['csv_writers']['shares']['writer']
                writer.writerow([
                    timestamp_now,
                    getattr(event.user, 'unique_id', ''),
                    getattr(event.user, 'nickname', ''),
                    getattr(event, 'share_type', 0),
                    getattr(event, 'share_target', 'unknown'),
                    getattr(event, 'share_count', 0),
                    getattr(event, 'users_joined', 0) or 0,
                    getattr(event, 'action', 0)
                ])
                recording_info['csv_writers']['shares']['file_handle'].flush()
            except Exception as e:
                if recording_info.get('is_recording', False):  # Only log if we should still be recording
                    self.logger.error(f"Error writing share event: {e}")

        @client.on(JoinEvent)
        async def on_join(event: JoinEvent):
            # Check if recording is still active
            if not recording_info.get('is_recording', False):
                return

            timestamp_now = datetime.now().isoformat()
            recording_info['stats']['joins'] += 1

            try:
                writer = recording_info['csv_writers']['joins']['writer']
                writer.writerow([
                    timestamp_now,
                    getattr(event.user, 'unique_id', ''),
                    getattr(event.user, 'nickname', ''),
                    getattr(event, 'count', 0),
                    getattr(event, 'is_top_user', False),
                    getattr(event, 'enter_type', 0),
                    getattr(event, 'action', 0),
                    getattr(event, 'user_share_type', ''),
                    getattr(event, 'client_enter_source', '')
                ])
                recording_info['csv_writers']['joins']['file_handle'].flush()
            except Exception as e:
                if recording_info.get('is_recording', False):  # Only log if we should still be recording
                    self.logger.error(f"Error writing join event: {e}")

    async def stop_recording(self, username: str, reason: str = "manual"):
        """Stop recording a streamer"""
        if username not in self.active_recordings:
            self.logger.warning(f"No active recording found for {username}")
            return

        recording_info = self.active_recordings[username]
        duration = (datetime.now() - recording_info['start_time']).total_seconds() / 60

        try:
            client = recording_info['client']

            # Mark recording as stopped to prevent new events from writing
            recording_info['is_recording'] = False
            self.logger.debug(f"Marked recording as stopped for {username}")

            # Stop video recording properly with multiple attempts
            if hasattr(client.web, 'fetch_video_data'):
                try:
                    if client.web.fetch_video_data.is_recording:
                        self.logger.info(f"🎬 Stopping video recording for {username}...")
                        client.web.fetch_video_data.stop()

                        # Give it a moment to finalize the file
                        await asyncio.sleep(2)

                        # Check if video file exists and has content
                        video_file = recording_info.get('video_file')
                        if video_file and Path(video_file).exists():
                            file_size = Path(video_file).stat().st_size / (1024 * 1024)  # MB
                            self.logger.info(f"📁 Video file size: {file_size:.1f} MB")

                            if file_size < 0.1:  # Less than 100KB might indicate corruption
                                self.logger.warning(f"⚠️  Video file seems very small, might be corrupted")
                        else:
                            self.logger.warning(f"⚠️  Video file not found: {video_file}")

                except Exception as video_error:
                    self.logger.error(f"Error stopping video recording: {video_error}")

            # Disconnect client gracefully first
            if client.connected:
                self.logger.debug(f"Disconnecting client for {username}")
                await client.disconnect()
                # Give extra time for events to finish processing
                await asyncio.sleep(2)

            # Close CSV file handles properly after disconnect
            if 'csv_writers' in recording_info:
                self.logger.debug(f"Closing CSV files for {username}")
                for csv_type, csv_info in recording_info['csv_writers'].items():
                    try:
                        csv_info['file_handle'].close()
                        self.logger.debug(f"Closed {csv_type} CSV file for {username}")
                    except Exception as e:
                        self.logger.debug(f"Error closing {csv_type} CSV file: {e}")

            # Log session info
            self.log_session_event(
                username,
                f'recording_stopped_{reason}',
                'success',
                duration,
                recording_info['stats']
            )

            self.logger.info(f"⏹️  Stopped recording {username} ({reason}) - Duration: {duration:.1f}m")
            self.logger.info(f"📊 Stats: {recording_info['stats']}")

        except Exception as e:
            self.logger.error(f"Error stopping recording for {username}: {e}")
        finally:
            del self.active_recordings[username]

    async def monitor_streamers(self):
        """Main monitoring loop"""
        self.logger.info("🔍 Starting TikTok streamer monitor...")
        self.logger.info(f"🖥️  Platform: {platform.system()} {platform.release()}")
        self.logger.info(f"📋 Monitoring {len([s for s in self.config['streamers'].values() if s.get('enabled', True)])} streamers")
        self.logger.info("📄 Control files:")
        self.logger.info(f"   • Create '{self.stop_file}' to stop monitoring gracefully")
        self.logger.info(f"   • Create '{self.pause_file}' to pause monitoring temporarily")
        self.logger.info(f"   • Check '{self.status_file}' for current status")
        self.logger.info(f"   • Edit '{self.config_file}' to modify streamers list (auto-reloads)")

        known_live_streamers: Set[str] = set()
        check_count = 0

        self.update_status_file("monitoring", "Started monitoring loop")

        while self.monitoring:
            try:
                # Check for config file changes first
                config_changed = self.check_config_changes()

                # Check for control signals
                control_signal = self.check_control_signals()

                if control_signal.startswith("stop:"):
                    reason = control_signal.split(":", 1)[1]
                    self.logger.info(f"🛑 Received stop signal: {reason}")
                    self.monitoring = False
                    self.update_status_file("stopping", f"Stop signal received: {reason}")
                    break

                elif control_signal.startswith("pause:"):
                    duration = int(control_signal.split(":", 1)[1])
                    self.logger.info(f"⏸️  Pausing monitoring for {duration} seconds...")
                    self.update_status_file("paused", f"Paused for {duration} seconds")

                    # Remove pause file and wait
                    if self.pause_file.exists():
                        self.pause_file.unlink()

                    await asyncio.sleep(duration)
                    self.logger.info("▶️  Resuming monitoring...")
                    self.update_status_file("monitoring", "Resumed after pause")
                    continue

                check_count += 1
                start_time = asyncio.get_event_loop().time()

                enabled_streamers = {
                    k: v for k, v in self.config['streamers'].items()
                    if v.get('enabled', True)
                }

                self.logger.debug(f"🔄 Check cycle #{check_count} - Checking {len(enabled_streamers)} streamers in parallel...")

                # Check all streamers in parallel
                live_status = await self.check_all_streamers_parallel(enabled_streamers)

                # Count results for summary
                total_checked = len(live_status)
                currently_live = [username for username, is_live in live_status.items() if is_live]

                # Process the results
                newly_live = []
                newly_offline = []

                for username, is_live in live_status.items():
                    if is_live and username not in known_live_streamers:
                        # Streamer just went live
                        newly_live.append(username)
                        known_live_streamers.add(username)

                    elif not is_live and username in known_live_streamers:
                        # Streamer went offline
                        newly_offline.append(username)
                        known_live_streamers.discard(username)

                # Handle newly live streamers
                for username in newly_live:
                    self.logger.info(f"🟢 {username} went LIVE!")
                    asyncio.create_task(self.start_recording(username))

                # Handle newly offline streamers
                for username in newly_offline:
                    self.logger.info(f"🔴 {username} went OFFLINE")
                    if username in self.active_recordings:
                        asyncio.create_task(self.stop_recording(username, "stream_ended"))

                # Calculate check duration
                check_duration = asyncio.get_event_loop().time() - start_time

                # Update status file
                self.update_status_file("monitoring", f"Check #{check_count}, duration: {check_duration:.1f}s")

                # Status update with cleaner output
                status_msg_parts = [f"📊 Checked {total_checked} streamers"]
                if config_changed:
                    status_msg_parts.append("🔄 Config reloaded")
                if currently_live:
                    status_msg_parts.append(f"📺 Live: {', '.join(currently_live)}")
                else:
                    status_msg_parts.append("💤 None live")
                status_msg_parts.append(f"⏱️ {check_duration:.1f}s")

                if check_count % 5 == 0 or newly_live or newly_offline or config_changed:  # Show status every 5 cycles or when changes occur
                    self.logger.info(" | ".join(status_msg_parts))
                elif check_count % 20 == 0:  # Minimal status every 20 cycles
                    self.logger.info(f"📊 Check #{check_count} | {total_checked} streamers | {len(currently_live)} live | ⏱️ {check_duration:.1f}s")

                # Dynamic sleep adjustment based on check duration
                base_interval = self.config['settings']['check_interval_seconds']
                adjusted_interval = max(5, base_interval - check_duration)  # Minimum 5 seconds

                if check_duration > base_interval * 0.8:  # If check takes more than 80% of interval
                    self.logger.warning(f"⚠️  Check cycle took {check_duration:.1f}s (target: {base_interval}s)")

                await asyncio.sleep(adjusted_interval)

            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                self.update_status_file("error", f"Error in monitoring loop: {e}")
                await asyncio.sleep(30)  # Wait longer on error

    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        signal_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
        self.logger.info(f"🛑 Received signal {signal_name} ({signum}). Shutting down...")
        self.monitoring = False

        # Stop all active recordings
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                for username in list(self.active_recordings.keys()):
                    loop.create_task(self.stop_recording(username, "shutdown"))
        except Exception as e:
            self.logger.error(f"Error handling signal: {e}")

    async def run(self):
        """Run the monitor"""
        try:
            await self.monitor_streamers()
        except KeyboardInterrupt:
            self.logger.info("👋 Monitor stopped by user (Ctrl+C)")
        finally:
            # Cleanup
            self.update_status_file("shutting_down", "Cleaning up active recordings")
            for username in list(self.active_recordings.keys()):
                await self.stop_recording(username, "shutdown")

            # Clean up control files
            self.cleanup_control_files()

            # Final status update
            self.update_status_file("stopped", "Monitor shutdown complete")
            self.logger.info("🏁 Monitor shutdown complete")

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='TikTok Live Stream Monitor - Automatically record streamers when they go live',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tiktok_monitor.py
  python tiktok_monitor.py --session-id your_session_id_here
  python tiktok_monitor.py --config custom_config.json --session-id abc123
  python tiktok_monitor.py --session-id abc123 --data-center eu-ttp2

Windows Examples:
  python.exe tiktok_monitor.py
  py -3 tiktok_monitor.py --session-id your_session_id_here
        """
    )

    parser.add_argument(
        '--session-id', '-s',
        type=str,
        help='TikTok session ID for accessing age-restricted streams'
    )

    parser.add_argument(
        '--config', '-c',
        type=str,
        default='streamers_config.json',
        help='Path to configuration file (default: streamers_config.json)'
    )

    parser.add_argument(
        '--data-center', '-d',
        type=str,
        help='TikTok data center (e.g., us-eastred, eu-ttp2) - overrides config file'
    )

    parser.add_argument(
        '--check-interval', '-i',
        type=int,
        help='How often to check for live streams in seconds (overrides config)'
    )

    parser.add_argument(
        '--output-dir', '-o',
        type=str,
        help='Output directory for recordings (overrides config)'
    )

    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )

    return parser.parse_args()

def main():
    """Main entry point"""
    args = parse_args()

    # Windows-specific console setup
    if platform.system() == "Windows":
        try:
            # Enable ANSI escape sequences on Windows 10+
            import subprocess
            subprocess.run("", shell=True, check=True)

            # Set console to UTF-8 if possible
            try:
                import sys
                import codecs
                sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
                sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')
            except:
                pass
        except:
            pass

    print("🚀 TikTok Live Stream Monitor Starting...")
    print(f"🖥️  Platform: {platform.system()} {platform.release()}")
    print(f"📁 Configuration file: {args.config}")

    if args.session_id:
        print("🔑 Session ID provided via command line")
    if args.data_center:
        print(f"🌍 Data center: {args.data_center}")
    if args.verbose:
        print("📝 Verbose logging enabled")

    print("📊 Session logs will be saved to: monitoring_sessions_[date].csv")
    print("📝 Debug logs will be saved to: monitor_[date].log")
    print("📄 Control options:")
    print("   • Create 'stop_monitor.txt' to stop monitoring gracefully")
    print("   • Create 'pause_monitor.txt' to pause monitoring temporarily")
    print("   • Check 'monitor_status.txt' for current status")
    print("   • Edit config file to modify streamers (auto-reloads)")

    if platform.system() == "Windows":
        print("⏹️  Press Ctrl+C or Ctrl+Break for immediate stop")
        print("💡 Windows users: Use 'py -3' instead of 'python3' if needed")
    else:
        print("⏹️  Press Ctrl+C for immediate stop")
    print()

    # Create monitor with command line arguments
    try:
        monitor = StreamMonitor(
            config_file=args.config,
            session_id=args.session_id
        )
    except Exception as e:
        print(f"❌ Failed to initialize monitor: {e}")
        if platform.system() == "Windows":
            print("💡 Windows troubleshooting:")
            print("   • Make sure Python is in your PATH")
            print("   • Try running as administrator if file permissions are an issue")
            print("   • Check that all required Python packages are installed")
        sys.exit(1)

    # Apply command line overrides
    if args.data_center:
        monitor.config['settings']['tt_target_idc'] = args.data_center
        monitor.logger.info(f"🌍 Data center overridden to: {args.data_center}")

    if args.check_interval:
        monitor.config['settings']['check_interval_seconds'] = args.check_interval
        monitor.logger.info(f"⏱️  Check interval overridden to: {args.check_interval}s")

    if args.output_dir:
        monitor.config['settings']['output_directory'] = args.output_dir
        monitor.logger.info(f"📁 Output directory overridden to: {args.output_dir}")

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        # Re-enable verbose logs if explicitly requested
        logging.getLogger("TikTokLive").setLevel(logging.DEBUG)
        logging.getLogger("httpx").setLevel(logging.INFO)
        monitor.logger.info("📝 Verbose logging enabled")

    try:
        if platform.system() == "Windows":
            # Windows-specific event loop policy for better compatibility
            try:
                asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            except AttributeError:
                # Fallback for older Python versions
                pass

        asyncio.run(monitor.run())
    except KeyboardInterrupt:
        print("\n👋 Monitor stopped by user")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        if platform.system() == "Windows":
            print("💡 Windows troubleshooting:")
            print("   • Check Windows Defender/Antivirus isn't blocking the script")
            print("   • Ensure you have proper internet connectivity")
            print("   • Try running the script from Command Prompt as administrator")
        sys.exit(1)

if __name__ == "__main__":
    main()
