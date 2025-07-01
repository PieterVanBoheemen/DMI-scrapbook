import pandas as pd
import time
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import os
import random

# === CONFIG ===
CONFIG = {
    "input_comments": "b.i.w.a.k_20250701_075347_comments.csv",
    "input_joins": "b.i.w.a.k_20250701_075347_joins.csv",
    "output_file": "users_videos.csv",
    "min_interactions": 2,
    "max_users": 100,
    "videos_per_user": 20,
    "delay_between_users": (2, 5),
    "scroll_pause": 1,
    "max_scrolls": 10
}


def load_users_from_csv(comments_path, joins_path, min_interactions=1):
    """Load and deduplicate users from comments and joins CSV files."""
    comments = pd.read_csv(comments_path)
    joins = pd.read_csv(joins_path)

    comments["interaction_type"] = "comment"
    joins["interaction_type"] = "join"

    comments = comments[["user_id", "nickname", "interaction_type"]]
    joins = joins[["user_id", "nickname", "interaction_type"]]

    all_users = pd.concat([comments, joins])
    user_counts = all_users.groupby("user_id").agg({
        "nickname": "first",
        "interaction_type": "count"
    }).reset_index()

    filtered = user_counts[user_counts["interaction_type"] >= min_interactions]
    return filtered


def get_recent_tiktok_posts(username, max_posts=20, scroll_pause=1, max_scrolls=10):
    url = f"https://www.tiktok.com/@{username.lstrip('@')}"
    options = uc.ChromeOptions()
    # Open visible browser
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = uc.Chrome(options=options)
    driver.set_window_size(1280, 800)

    try:
        driver.get(url)
        time.sleep(3)

        video_urls = set()
        scrolls = 0
        last_height = driver.execute_script("return document.body.scrollHeight")

        while len(video_urls) < max_posts and scrolls < max_scrolls:
            links = driver.find_elements(By.XPATH, '//a[contains(@href, "/video/")]')
            for link in links:
                href = link.get_attribute("href")
                if "/video/" in href:
                    video_urls.add(href)
                    if len(video_urls) >= max_posts:
                        break

            driver.find_element(By.TAG_NAME, "body").send_keys(Keys.END)
            time.sleep(scroll_pause)
            scrolls += 1
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        return list(video_urls)[:max_posts]

    except (TimeoutException, NoSuchElementException) as e:
        print(f"[ERROR] Failed for @{username}: {e}")
        return []

    finally:
        time.sleep(2)
        driver.quit()


def main():
    users_df = load_users_from_csv(CONFIG["input_comments"], CONFIG["input_joins"], CONFIG["min_interactions"])
    users_df = users_df.head(CONFIG["max_users"])

    output_rows = []

    for idx, row in users_df.iterrows():
        user_id = row["user_id"]
        print(f"[{idx+1}/{len(users_df)}] Scraping posts for {user_id}...")
        try:
            video_urls = get_recent_tiktok_posts(user_id, max_posts=CONFIG["videos_per_user"],
                                                 scroll_pause=CONFIG["scroll_pause"],
                                                 max_scrolls=CONFIG["max_scrolls"])
            for url in video_urls:
                output_rows.append({"user_id": user_id, "video_url": url})
        except Exception as e:
            print(f"[WARN] Skipped {user_id} due to error: {e}")
        time.sleep(random.uniform(*CONFIG["delay_between_users"]))

    out_df = pd.DataFrame(output_rows)
    out_df.to_csv(CONFIG["output_file"], index=False)
    print(f"\n✅ Done. Saved {len(out_df)} video links to {CONFIG['output_file']}")

    # Save plain list of video URLs (one per line)
    with open("video_urls.txt", "w") as f:
        for row in output_rows:
            f.write(f"{row['video_url']}\n")

    print(f"📄 Saved plain video URL list to video_urls.txt")


if __name__ == "__main__":
    main()
