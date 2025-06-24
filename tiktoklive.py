import asyncio
import csv
import os
from datetime import datetime

from TikTokLive.client.client import TikTokLiveClient
from TikTokLive.client.logger import LogLevel
from TikTokLive.events import ConnectEvent, DisconnectEvent, CommentEvent, GiftEvent
from TikTokLive.events.custom_events import FollowEvent, ShareEvent
from TikTokLive.events.proto_events import JoinEvent

# Configuration
STREAMER_USERNAME = "@pubgmobileofficialid"  # Change this to the desired streamer
SESSION_ID = "820ec611d99f71bc20e5398a737fdd48"  # Your session ID for age-restricted streams
TT_TARGET_IDC = "us-eastred"  # Data center for your session

# Set environment variable to whitelist the sign server (required for session ID)
if SESSION_ID:
    os.environ['WHITELIST_AUTHENTICATED_SESSION_ID_HOST'] = 'tiktok.eulerstream.com'
    print("🔐 Whitelisted sign server for session ID authentication")

# Create client
client: TikTokLiveClient = TikTokLiveClient(unique_id=STREAMER_USERNAME)

# Set session ID if needed for age-restricted content
if SESSION_ID:
    try:
        client.web.set_session(SESSION_ID, TT_TARGET_IDC)
        print(f"🔑 Session ID set for age-restricted content (Data center: {TT_TARGET_IDC})")
    except Exception as e:
        print(f"⚠️  Could not set session ID: {e}")

# Create CSV files with timestamp
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
username = STREAMER_USERNAME.replace("@", "")

# Ensure recordings directory exists
os.makedirs("recordings", exist_ok=True)

comments_csv = f"recordings/{username}_{timestamp}_comments.csv"
gifts_csv = f"recordings/{username}_{timestamp}_gifts.csv"
follows_csv = f"recordings/{username}_{timestamp}_follows.csv"
shares_csv = f"recordings/{username}_{timestamp}_shares.csv"
joins_csv = f"recordings/{username}_{timestamp}_joins.csv"

# Initialize CSV files with headers
with open(comments_csv, 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(['timestamp', 'user_id', 'nickname', 'comment', 'follower_count'])

with open(gifts_csv, 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(['timestamp', 'user_id', 'nickname', 'gift_name', 'repeat_count', 'streakable', 'streaking'])

with open(follows_csv, 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(['timestamp', 'user_id', 'nickname', 'follow_count', 'share_type', 'action'])

with open(shares_csv, 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(['timestamp', 'user_id', 'nickname', 'share_type', 'share_target', 'share_count', 'users_joined', 'action'])

with open(joins_csv, 'w', newline='', encoding='utf-8') as f:
    writer = csv.writer(f)
    writer.writerow(['timestamp', 'user_id', 'nickname', 'count', 'is_top_user', 'enter_type', 'action', 'user_share_type', 'client_enter_source'])

print(f"📁 CSV files will be saved as:")
print(f"   Comments: {comments_csv}")
print(f"   Gifts: {gifts_csv}")
print(f"   Follows: {follows_csv}")
print(f"   Shares: {shares_csv}")
print(f"   Joins: {joins_csv}")

# Recording
@client.on(ConnectEvent)
async def on_connect(event: ConnectEvent):
    client.logger.info("Connected!")
    print(f"✅ Connected to @{event.unique_id}'s live stream!")

    # Start a recording
    video_file = f"recordings/{username}_{timestamp}.mp4"
    try:
        client.web.fetch_video_data.start(
            output_fp=video_file,
            room_info=client.room_info,
            output_format="mp4"
        )
        print(f"🎥 Started recording video: {video_file}")
    except Exception as e:
        print(f"❌ Failed to start video recording: {e}")

# Comments in chat
async def on_comment(event: CommentEvent) -> None:
    timestamp_now = datetime.now().isoformat()

    # Print to console
    print(f"💬 {event.user.nickname}: {event.comment}")

    # Save to CSV
    with open(comments_csv, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            timestamp_now,
            getattr(event.user, 'unique_id', ''),
            getattr(event.user, 'nickname', ''),
            event.comment,
            getattr(event.user, 'follower_count', 0)
        ])

client.add_listener(CommentEvent, on_comment)

# Gifts
@client.on(GiftEvent)
async def on_gift(event: GiftEvent):
    timestamp_now = datetime.now().isoformat()

    client.logger.info("Received a gift!")

    # Print to console
    if event.gift.streakable and not event.streaking:
        print(f"🎁 {event.user.nickname} sent {event.repeat_count}x \"{event.gift.name}\"")
    elif not event.gift.streakable:
        print(f"🎁 {event.user.nickname} sent \"{event.gift.name}\"")

    # Save to CSV
    with open(gifts_csv, 'a', newline='', encoding='utf-8') as f:
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

# Follows
@client.on(FollowEvent)
async def on_follow(event: FollowEvent):
    timestamp_now = datetime.now().isoformat()

    client.logger.info("New follow!")

    # Print to console
    print(f"👤 {event.user.nickname} followed the streamer!")

    # Save to CSV
    with open(follows_csv, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            timestamp_now,
            getattr(event.user, 'unique_id', ''),
            getattr(event.user, 'nickname', ''),
            getattr(event, 'follow_count', 0),
            getattr(event, 'share_type', 0),
            getattr(event, 'action', 0)
        ])

# User Joins
@client.on(JoinEvent)
async def on_join(event: JoinEvent):
    timestamp_now = datetime.now().isoformat()

    # Print to console
    join_msg = f"🚪 {event.user.nickname} joined the stream"

    # Add extra info if available
    if getattr(event, 'is_top_user', False):
        join_msg += " (⭐ Top User)"
    if getattr(event, 'user_share_type', None):
        join_msg += f" via {event.user_share_type}"

    print(join_msg)

    # Save to CSV
    with open(joins_csv, 'a', newline='', encoding='utf-8') as f:
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

# Shares
@client.on(ShareEvent)
async def on_share(event: ShareEvent):
    timestamp_now = datetime.now().isoformat()

    client.logger.info("Stream shared!")

    # Print to console
    users_joined = getattr(event, 'users_joined', 0) or 0
    share_target = getattr(event, 'share_target', 'unknown')
    print(f"📤 {event.user.nickname} shared the stream to {share_target}")
    if users_joined > 0:
        print(f"   👥 {users_joined} users joined from this share!")

    # Save to CSV
    with open(shares_csv, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            timestamp_now,
            getattr(event.user, 'unique_id', ''),
            getattr(event.user, 'nickname', ''),
            getattr(event, 'share_type', 0),
            share_target,
            getattr(event, 'share_count', 0),
            users_joined,
            getattr(event, 'action', 0)
        ])

@client.on(DisconnectEvent)
async def on_live_end(_: DisconnectEvent):
    """Stop the download when we disconnect"""
    client.logger.info("Disconnected!")

    if client.web.fetch_video_data.is_recording:
        client.web.fetch_video_data.stop()

    # Print session summary
    try:
        with open(comments_csv, 'r', encoding='utf-8') as f:
            comment_count = sum(1 for line in f) - 1  # Subtract header

        with open(gifts_csv, 'r', encoding='utf-8') as f:
            gift_count = sum(1 for line in f) - 1  # Subtract header

        with open(follows_csv, 'r', encoding='utf-8') as f:
            follow_count = sum(1 for line in f) - 1  # Subtract header

        with open(shares_csv, 'r', encoding='utf-8') as f:
            share_count = sum(1 for line in f) - 1  # Subtract header

        with open(joins_csv, 'r', encoding='utf-8') as f:
            join_count = sum(1 for line in f) - 1  # Subtract header

        print(f"\n📊 Session Summary:")
        print(f"   Comments captured: {comment_count}")
        print(f"   Gifts captured: {gift_count}")
        print(f"   Follows captured: {follow_count}")
        print(f"   Shares captured: {share_count}")
        print(f"   Joins captured: {join_count}")
        print(f"   Files saved in: recordings/")
    except Exception as e:
        print(f"Error generating summary: {e}")

if __name__ == '__main__':
    print(f"🔴 Starting TikTok Live recorder for {STREAMER_USERNAME}")
    print("⏹️  Press Ctrl+C to stop recording\n")

    # Enable download info
    client.logger.setLevel(LogLevel.INFO.value)

    # Need room info to download stream
    try:
        client.run(fetch_room_info=True)
    except KeyboardInterrupt:
        print("\n⏹️  Recording stopped by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        if "age restricted" in str(e).lower():
            print("💡 This stream may require a valid session ID")
        elif "not live" in str(e).lower():
            print("💡 The streamer is not currently live")
    finally:
        print("🏁 Recorder stopped.")
