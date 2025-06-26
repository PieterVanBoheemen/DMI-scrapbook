import asyncio
import csv
import json
import os
import signal
import sys
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
import logging

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
        self.active_recordings: Dict[str, TikTokLiveClient] = {}
        self.monitoring = True
        self.session_log_file = f"monitoring_sessions_{datetime.now().strftime('%Y%m%d')}.csv"

        # Override config session_id if provided via command line (after config is loaded)
        if self.global_session_id:
            self.config['settings']['session_id'] = self.global_session_id

        # Set up logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(f"monitor_{datetime.now().strftime('%Y%m%d')}.log"),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)

        # Log session ID usage
        if self.global_session_id:
            self.logger.info(f"🔑 Using session ID from command line argument")
        elif self.config['settings'].get('session_id'):
            self.logger.info(f"🔑 Using session ID from config file")
        else:
            self.logger.info("ℹ️  No session ID provided - only public streams accessible")

        # Initialize session log
        self.init_session_log()

        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

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

        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.error(f"Error loading config: {e}")
                return default_config
        else:
            # Create default config file
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=2)
            self.logger.info(f"Created default config file: {self.config_file}")
            return default_config

    def init_session_log(self):
        """Initialize the session monitoring log CSV"""
        if not os.path.exists(self.session_log_file):
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
            client = TikTokLiveClient(unique_id=username)

            # Set session ID if available
            streamer_config = self.config['streamers'].get(username.replace('@', ''), {})
            session_id = streamer_config.get('session_id') or self.config['settings'].get('session_id')
            tt_target_idc = streamer_config.get('tt_target_idc') or self.config['settings'].get('tt_target_idc')

            if session_id:
                client.web.set_session(session_id, tt_target_idc)

            is_live = await client.is_live()
            return is_live

        except Exception as e:
            self.logger.debug(f"Error checking {username}: {e}")
            return False

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

            # Set environment variable for sign server
            whitelist_host = self.config['settings'].get('whitelist_sign_server')
            if whitelist_host:
                os.environ['WHITELIST_AUTHENTICATED_SESSION_ID_HOST'] = whitelist_host

            # Create client
            client = TikTokLiveClient(unique_id=username)

            # Set session ID if available
            streamer_config = self.config['streamers'].get(username.replace('@', ''), {})
            session_id = streamer_config.get('session_id') or self.config['settings'].get('session_id')
            tt_target_idc = streamer_config.get('tt_target_idc') or self.config['settings'].get('tt_target_idc')

            if session_id:
                client.web.set_session(session_id, tt_target_idc)

            # Set up file paths
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            username_clean = username.replace("@", "")
            output_dir = self.config['settings']['output_directory']
            os.makedirs(output_dir, exist_ok=True)

            # Create CSV files
            csv_files = {
                'comments': f"{output_dir}/{username_clean}_{timestamp}_comments.csv",
                'gifts': f"{output_dir}/{username_clean}_{timestamp}_gifts.csv",
                'follows': f"{output_dir}/{username_clean}_{timestamp}_follows.csv",
                'shares': f"{output_dir}/{username_clean}_{timestamp}_shares.csv",
                'joins': f"{output_dir}/{username_clean}_{timestamp}_joins.csv"
            }

            # Initialize CSV files
            self.init_csv_files(csv_files)

            # Store recording info
            recording_info = {
                'client': client,
                'start_time': datetime.now(),
                'csv_files': csv_files,
                'stats': {'comments': 0, 'gifts': 0, 'follows': 0, 'shares': 0, 'joins': 0}
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

    def init_csv_files(self, csv_files: dict):
        """Initialize CSV files with headers"""
        headers = {
            'comments': ['timestamp', 'user_id', 'nickname', 'comment', 'follower_count'],
            'gifts': ['timestamp', 'user_id', 'nickname', 'gift_name', 'repeat_count', 'streakable', 'streaking'],
            'follows': ['timestamp', 'user_id', 'nickname', 'follow_count', 'share_type', 'action'],
            'shares': ['timestamp', 'user_id', 'nickname', 'share_type', 'share_target', 'share_count', 'users_joined', 'action'],
            'joins': ['timestamp', 'user_id', 'nickname', 'count', 'is_top_user', 'enter_type', 'action', 'user_share_type', 'client_enter_source']
        }

        for csv_type, filepath in csv_files.items():
            with open(filepath, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(headers[csv_type])

    def setup_event_handlers(self, client: TikTokLiveClient, username: str, recording_info: dict):
        """Set up event handlers for the client"""

        @client.on(ConnectEvent)
        async def on_connect(event: ConnectEvent):
            self.logger.info(f"📡 Connected to {username}'s stream (Room: {client.room_id})")

            # Start video recording
            timestamp = recording_info['start_time'].strftime("%Y%m%d_%H%M%S")
            username_clean = username.replace("@", "")
            video_file = f"{self.config['settings']['output_directory']}/{username_clean}_{timestamp}.mp4"

            try:
                client.web.fetch_video_data.start(
                    output_fp=video_file,
                    room_info=client.room_info,
                    output_format="mp4"
                )
                self.logger.info(f"🎥 Started video recording: {video_file}")
            except Exception as e:
                self.logger.error(f"Failed to start video recording for {username}: {e}")

        @client.on(DisconnectEvent)
        async def on_disconnect(event: DisconnectEvent):
            await self.stop_recording(username, "stream_ended")

        @client.on(CommentEvent)
        async def on_comment(event: CommentEvent):
            timestamp_now = datetime.now().isoformat()
            recording_info['stats']['comments'] += 1

            with open(recording_info['csv_files']['comments'], 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    timestamp_now,
                    getattr(event.user, 'unique_id', ''),
                    getattr(event.user, 'nickname', ''),
                    event.comment,
                    getattr(event.user, 'follower_count', 0)
                ])

        @client.on(GiftEvent)
        async def on_gift(event: GiftEvent):
            timestamp_now = datetime.now().isoformat()
            recording_info['stats']['gifts'] += 1

            with open(recording_info['csv_files']['gifts'], 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    timestamp_now,
                    getattr(event.user, 'unique_id', ''),
                    getattr(event.user, 'nickname', ''),
                    event.gift.name,
                    event.repeat_count,
                    event.gift.streakable,
                    event.streaking
                ])

        @client.on(FollowEvent)
        async def on_follow(event: FollowEvent):
            timestamp_now = datetime.now().isoformat()
            recording_info['stats']['follows'] += 1

            with open(recording_info['csv_files']['follows'], 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    timestamp_now,
                    getattr(event.user, 'unique_id', ''),
                    getattr(event.user, 'nickname', ''),
                    getattr(event, 'follow_count', 0),
                    getattr(event, 'share_type', 0),
                    getattr(event, 'action', 0)
                ])

        @client.on(ShareEvent)
        async def on_share(event: ShareEvent):
            timestamp_now = datetime.now().isoformat()
            recording_info['stats']['shares'] += 1

            with open(recording_info['csv_files']['shares'], 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
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

        @client.on(JoinEvent)
        async def on_join(event: JoinEvent):
            timestamp_now = datetime.now().isoformat()
            recording_info['stats']['joins'] += 1

            with open(recording_info['csv_files']['joins'], 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
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

    async def stop_recording(self, username: str, reason: str = "manual"):
        """Stop recording a streamer"""
        if username not in self.active_recordings:
            self.logger.warning(f"No active recording found for {username}")
            return

        recording_info = self.active_recordings[username]
        duration = (datetime.now() - recording_info['start_time']).total_seconds() / 60

        try:
            # Stop video recording
            client = recording_info['client']
            if hasattr(client.web, 'fetch_video_data') and client.web.fetch_video_data.is_recording:
                client.web.fetch_video_data.stop()

            # Disconnect client
            if client.connected:
                await client.disconnect()

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
        self.logger.info(f"📋 Monitoring {len([s for s in self.config['streamers'].values() if s.get('enabled', True)])} streamers")

        known_live_streamers: Set[str] = set()

        while self.monitoring:
            try:
                enabled_streamers = {
                    k: v for k, v in self.config['streamers'].items()
                    if v.get('enabled', True)
                }

                # Check each enabled streamer
                for streamer_key, streamer_config in enabled_streamers.items():
                    username = streamer_config['username']

                    try:
                        is_live = await self.check_streamer_status(username)

                        if is_live and username not in known_live_streamers:
                            # Streamer just went live
                            self.logger.info(f"🟢 {username} went LIVE!")
                            known_live_streamers.add(username)
                            await self.start_recording(username)

                        elif not is_live and username in known_live_streamers:
                            # Streamer went offline
                            self.logger.info(f"🔴 {username} went OFFLINE")
                            known_live_streamers.discard(username)
                            if username in self.active_recordings:
                                await self.stop_recording(username, "stream_ended")

                        # Small delay between checks
                        await asyncio.sleep(1)

                    except Exception as e:
                        self.logger.debug(f"Error checking {username}: {e}")

                # Status update
                if known_live_streamers:
                    self.logger.info(f"📺 Currently live: {', '.join(known_live_streamers)}")
                else:
                    self.logger.info("💤 No streamers currently live")

                # Wait before next check cycle
                await asyncio.sleep(self.config['settings']['check_interval_seconds'])

            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(30)  # Wait longer on error

    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info(f"🛑 Received signal {signum}. Shutting down...")
        self.monitoring = False

        # Stop all active recordings
        loop = asyncio.get_event_loop()
        for username in list(self.active_recordings.keys()):
            loop.create_task(self.stop_recording(username, "shutdown"))

    async def run(self):
        """Run the monitor"""
        try:
            await self.monitor_streamers()
        except KeyboardInterrupt:
            self.logger.info("👋 Monitor stopped by user")
        finally:
            # Cleanup
            for username in list(self.active_recordings.keys()):
                await self.stop_recording(username, "shutdown")
            self.logger.info("🏁 Monitor shutdown complete")

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='TikTok Live Stream Monitor - Automatically record streamers when they go live',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 tiktok_monitor.py
  python3 tiktok_monitor.py --session-id your_session_id_here
  python3 tiktok_monitor.py --config custom_config.json --session-id abc123
  python3 tiktok_monitor.py --session-id abc123 --data-center eu-ttp2
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

    print("🚀 TikTok Live Stream Monitor Starting...")
    print(f"📁 Configuration file: {args.config}")

    if args.session_id:
        print("🔑 Session ID provided via command line")
    if args.data_center:
        print(f"🌍 Data center: {args.data_center}")
    if args.verbose:
        print("📝 Verbose logging enabled")

    print("📊 Session logs will be saved to: monitoring_sessions_[date].csv")
    print("📝 Debug logs will be saved to: monitor_[date].log")
    print("⏹️  Press Ctrl+C to stop monitoring\n")

    # Create monitor with command line arguments
    monitor = StreamMonitor(
        config_file=args.config,
        session_id=args.session_id
    )

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
        monitor.logger.info("📝 Verbose logging enabled")

    try:
        asyncio.run(monitor.run())
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
