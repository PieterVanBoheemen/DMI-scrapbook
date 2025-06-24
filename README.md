# DMI Scrapbook

This scrapbook contains scripts I used at the DMI summerschool 25

* tiktoklive.py TikTok Live Stream Recorder

## tiktoklive.py

### Intro

This Python-based tool enables researchers to capture and analyze real-time interactions during TikTok live streams. It records both video content and comprehensive user engagement data to CSV files, providing a complete dataset for social media research, audience analysis, and digital ethnography studies.

---

## Features & Capabilities

### 🎥 Video Recording
- **Automatic MP4 capture** of the entire live stream
- **Timestamped filenames** for organization
- **HD quality recording** when available

### 📊 Comprehensive Data Logging
The tool captures **five types of user interactions** in separate CSV files:

#### 1. **Comments** 💬
- Real-time chat messages
- User information (ID, nickname, follower count)
- Timestamps for temporal analysis

#### 2. **Gifts** 🎁
- Virtual gifts sent to streamers
- Gift types, values, and streaking behavior
- Monetary value analysis potential

#### 3. **Follows** 👤
- New followers during the stream
- Follow events with user metadata
- Growth tracking capabilities

#### 4. **Shares** 📤
- Stream sharing events
- Share destinations (WhatsApp, Instagram, etc.)
- **Users joined via shares** - tracks viral growth

#### 5. **User Joins** 🚪
- New viewers entering the stream
- Entry source tracking (direct, shared links, etc.)
- VIP/Top user identification

### 🔐 Age-Restricted Content Support
- Session ID authentication for accessing restricted streams
- Configurable data center routing
- Bypass age verification for research purposes

---

## Technical Requirements

### Dependencies
```bash
pip install TikTokLive asyncio csv
```

### System Requirements
- **Python 3.7+**
- **Stable internet connection**
- **~500MB free disk space** per hour of recording

### Platform Compatibility
- ✅ macOS
- ✅ Windows
- ✅ Linux

---

## Installation & Setup

### 1. Install Dependencies
```bash
pip install TikTokLive
```

### 2. Configure the Script
Edit the configuration section in the script:

```python
# Configuration
STREAMER_USERNAME = "@username"  # Target streamer
SESSION_ID = "your_session_id"   # For age-restricted content (optional)
TT_TARGET_IDC = "us-eastred"     # Data center (optional)
```

### 3. Set Up Authentication (If Needed)
For age-restricted streams, you'll need:
- A valid TikTok session ID
- Appropriate data center configuration

---

## Usage Instructions

### Basic Usage
```bash
python3 tiktoklive.py
```

### Output Structure
```
recordings/
├── username_20250624_143022.mp4           # Video file
├── username_20250624_143022_comments.csv  # Chat messages
├── username_20250624_143022_gifts.csv     # Virtual gifts
├── username_20250624_143022_follows.csv   # New followers
├── username_20250624_143022_shares.csv    # Share events
└── username_20250624_143022_joins.csv     # User joins
```

### Real-time Console Output
```
🔴 Starting TikTok Live recorder for @username
🔑 Session ID set for age-restricted content (Data center: us-eastred)
✅ Connected to @username's live stream!
🎥 Started recording video: recordings/username_20250624_143022.mp4

💬 user123: Hello everyone!
🎁 fan456 sent 5x "Rose"
👤 newbie789 followed the streamer!
📤 viral_user shared the stream to WhatsApp
   👥 3 users joined from this share!
🚪 guest101 joined the stream (⭐ Top User)
```

---

## Data Structure & Schema

### Comments CSV
| Column | Description | Example |
|--------|-------------|---------|
| timestamp | ISO timestamp | 2025-06-24T14:30:22.123456 |
| user_id | TikTok user ID | @user123 |
| nickname | Display name | "Cool User" |
| comment | Message content | "Great stream!" |
| follower_count | User's followers | 1500 |

### Gifts CSV
| Column | Description | Example |
|--------|-------------|---------|
| timestamp | ISO timestamp | 2025-06-24T14:30:22.123456 |
| user_id | Sender ID | @generous_fan |
| nickname | Sender name | "Generous Fan" |
| gift_name | Gift type | "Rose" |
| repeat_count | Quantity sent | 5 |
| streakable | Can be streaked | true |
| streaking | Currently streaking | false |

### Follows CSV
| Column | Description | Example |
|--------|-------------|---------|
| timestamp | ISO timestamp | 2025-06-24T14:30:22.123456 |
| user_id | New follower ID | @newfan |
| nickname | Follower name | "New Fan" |
| follow_count | Total follows | 150 |
| share_type | Follow trigger | 0 |
| action | Follow action type | 1 |

### Shares CSV
| Column | Description | Example |
|--------|-------------|---------|
| timestamp | ISO timestamp | 2025-06-24T14:30:22.123456 |
| user_id | Sharer ID | @viral_user |
| nickname | Sharer name | "Viral User" |
| share_type | Share method | 1 |
| share_target | Destination | "WhatsApp" |
| share_count | Total shares | 5 |
| users_joined | New users from share | 3 |
| action | Share action type | 1 |

### Joins CSV
| Column | Description | Example |
|--------|-------------|---------|
| timestamp | ISO timestamp | 2025-06-24T14:30:22.123456 |
| user_id | Joiner ID | @newviewer |
| nickname | Joiner name | "New Viewer" |
| count | Join count | 1 |
| is_top_user | VIP status | false |
| enter_type | Entry method | 0 |
| action | Join action | 1 |
| user_share_type | Entry source | "direct" |
| client_enter_source | Technical source | "web" |

---

## Research Considerations

### Ethical Guidelines
- **Informed Consent**: Consider notification requirements for public stream recording
- **Data Privacy**: Anonymize user data when publishing research
- **Platform Terms**: Ensure compliance with TikTok's Terms of Service
- **Institutional Review**: Obtain IRB approval when required

### Data Quality Notes
- **Real-time Accuracy**: All events are captured as they occur
- **Missing Data**: Individual user departures are not trackable via TikTok's API
- **Rate Limiting**: Extended recording sessions may encounter API limits
- **Stream Dependencies**: Tool requires active live streams to function

### Limitations
- ❌ **Cannot track users leaving** the stream
- ❌ **No historical data** - only captures live events
- ❌ **Platform dependent** - relies on TikTok's internal API
- ❌ **No user demographics** beyond follower counts

---

## Advanced Configuration

### Session Authentication
For age-restricted content research:

```python
# Obtain session ID from browser developer tools
SESSION_ID = "your_session_id_here"
TT_TARGET_IDC = "us-eastred"  # or "eu-ttp2" for Europe
```

### Environment Variables (Recommended)
```bash
export TIKTOK_SESSION_ID="your_session_id"
export WHITELIST_AUTHENTICATED_SESSION_ID_HOST="tiktok.eulerstream.com"
```

### Custom Output Directory
```python
OUTPUT_DIRECTORY = "research_data/tiktok_streams"
```

---

## Troubleshooting

### Common Issues

**"Stream is age-restricted"**
- Solution: Add valid session ID and data center configuration

**"User is not currently live"**
- Solution: Verify the streamer is actively broadcasting

**"Connection timeout"**
- Solution: Check internet connection and try different streamers

**"Rate limiting"**
- Solution: Wait 5-10 minutes before reconnecting

### Session Summary
At the end of each recording session:
```
📊 Session Summary:
   Comments captured: 245
   Gifts captured: 67
   Follows captured: 23
   Shares captured: 8
   Joins captured: 156
   Files saved in: recordings/
```

---

## Data Analysis Examples

### Python Analysis Starter
```python
import pandas as pd

# Load the data
comments = pd.read_csv('recordings/username_comments.csv')
gifts = pd.read_csv('recordings/username_gifts.csv')
joins = pd.read_csv('recordings/username_joins.csv')

# Basic analytics
print(f"Total comments: {len(comments)}")
print(f"Unique commenters: {comments['user_id'].nunique()}")
print(f"Most active user: {comments['user_id'].value_counts().head(1)}")

# Time-based analysis
comments['timestamp'] = pd.to_datetime(comments['timestamp'])
comments_per_minute = comments.set_index('timestamp').resample('1T').size()
```

### Research Questions This Tool Can Address
- How does engagement vary throughout a live stream?
- What triggers viral sharing behavior?
- How do gift-giving patterns correlate with content?
- What is the relationship between comments and new follows?
- How do entry sources affect user engagement?

---

## Citation & Attribution

When using this tool in research, please consider citing:

```
TikTok Live Stream Recorder [Computer software]. (2025).
Based on TikTokLive Python library by Isaac Kogan.
```

---

## Support & Contributions

### Known Limitations
- This is a reverse-engineering project, not an official API
- API changes may require tool updates
- Some events may be platform-version dependent

### Future Enhancements
- Real-time dashboard visualization
- Automated sentiment analysis
- Multi-stream concurrent recording
- Integration with other social platforms

---

## Legal Disclaimer

This tool is for academic and research purposes only. Users are responsible for:
- Complying with platform Terms of Service
- Obtaining necessary permissions for data collection
- Following institutional research guidelines
- Respecting user privacy and data protection laws

**Note**: This is an unofficial tool that reverse-engineers TikTok's internal API. It should not be used for commercial purposes or at scale without proper authorization.
