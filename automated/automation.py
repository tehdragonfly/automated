import os
import time

from datetime import datetime, timedelta
from redis import StrictRedis
from threading import Thread

from automated.db import Session, Category, Clockwheel, ClockwheelItem
from automated.helpers.play import play_song, queue_song
from automated.helpers.schedule import find_event, get_clockwheel, pick_song

# XXX PUT ALL THIS SHIT IN HELPERS

def populate_cw_items(cw):
    return Session.query(ClockwheelItem, Category).join(Category).filter(
        ClockwheelItem.clockwheel==cw
    ).order_by(ClockwheelItem.number).all() if cw is not None else []

# XXX DON'T PUT ANY OF THIS SHIT IN HELPERS

def play_queue():
    while running:
        t = time.time()
        # Cue things up 5 seconds ahead.
        play_items = redis.zrangebyscore("play_queue", t+4, t+5, withscores=True)
        for item_id, queue_time in play_items:
            item = redis.hgetall("item:"+item_id)
            if len(item)==0:
                redis.zrem("play_queue", item_id, item)
                continue
            if item["status"] != "queued":
                continue
            Thread(target=play_song, args=(queue_time, item_id, item)).start()
            redis.hset("item:"+item_id, "status", "preparing")
        time.sleep(0.01)

def scheduler():

    next_time = datetime.fromtimestamp(round(time.time()+5))
    next_event = find_event(next_time)
    cw = get_clockwheel(next_time)
    cw_items = populate_cw_items(cw)

    while running:

        # Trim playlist items older than the longest repetition limit.
        longest_limit = max(
            float(redis.get("song_limit")),
            float(redis.get("artist_limit")),
            float(redis.get("album_limit")),
        )
        old_items = redis.zrangebyscore("play_queue", 0, time.time() - longest_limit)
        for item_id in old_items:
            redis.zrem("play_queue", item_id)
            redis.delete("item:"+item_id)
            redis.delete("item:"+item_id+":artists")

        if False:

            print "PLANNING AHEAD."

            # Plan ahead
            pass

        else:

            print "IMPROVISING."

            # Improvise

            if cw is None or len(cw_items) == 0:

                # If there isn't a clockwheel, just pick any song.
                print "CLOCKWHEEL IS NONE, PICKING ANY SONG."
                song = pick_song(next_time)

            else:

                # Otherwise pick songs from the clockwheel.
                print "CURRENT CLOCKWHEEL IS", cw
                item, category = cw_items.pop(0)
                print "ITEM", item
                print "CATEGORY", category
                song = pick_song(next_time, category.id)

            # Skip if we can't find a song.
            # This allows us to move on if one category in the clockwheel is
            # exhausted, although it risks putting us into an infinite loop
            # if there aren't enough songs in the other categories.
            if song is not None:
                queue_song(next_time, song)
                next_time += song.length
                print "SELECTED", song
            else:
                print "NOTHING HERE, SKIPPING."

        # Pause if we've reached more than 30 minutes into the future.
        while next_time-datetime.now() > timedelta(0, 1800):
            print "SLEEPING"
            time.sleep(300)

        # Check if we need a new clockwheel
        # or if the item list needs repopulating.
        new_cw = get_clockwheel(next_time)
        if new_cw != cw or len(cw_items) == 0:
            print "REFRESHING CLOCKWHEEL."
            cw = get_clockwheel(next_time)
            cw_items = populate_cw_items(cw)

redis = StrictRedis()

# Set default values for repetition limits if they don't exist already.
if redis.get("song_limit") is None:
    redis.set("song_limit", 3600)
if redis.get("artist_limit") is None:
    redis.set("artist_limit", 3600)
if redis.get("album_limit") is None:
    redis.set("album_limit", 3600)

# Make sure any existing future items are cleared.
future_items = redis.zrangebyscore("play_queue", time.time(), "inf")
for item_id in future_items:
    redis.zrem("play_queue", item_id)
    redis.delete("item:"+item_id)

running = True

Thread(target=play_queue).start()

try:
    scheduler()
except:
    running = False
    raise

