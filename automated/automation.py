import os
import time

from datetime import datetime, timedelta
from redis import StrictRedis
from threading import Thread

from automated.db import Session, Category, Clockwheel, ClockwheelItem
from automated.helpers.plan import plan_attempt, shorten, lengthen
from automated.helpers.play import play_song, queue_song, queue_event
from automated.helpers.schedule import (
    find_event,
    get_clockwheel,
    populate_cw_items,
    pick_song,
)


def play_queue():
    while redis.get("running") is not None:
        t = time.time()
        # Cue things up 10 seconds ahead.
        play_items = redis.zrangebyscore("play_queue", t, t+10, withscores=True)
        for item_id, queue_time in play_items:
            item = redis.hgetall("item:"+item_id)
            if len(item) == 0:
                redis.zrem("play_queue", item_id, item)
                continue
            if item["status"] != "queued":
                continue
            Thread(target=play_song, args=(queue_time, item_id, item)).start()
            redis.hset("item:"+item_id, "status", "preparing")
        time.sleep(0.01)


def scheduler():

    next_time = datetime.fromtimestamp(round(time.time()+10))
    next_event = find_event(next_time)
    cw = get_clockwheel(next_time)
    cw_items = populate_cw_items(cw)

    while redis.get("running") is not None:

        # Trim playlist items older than the longest repetition limit.
        longest_limit = max(
            float(redis.get("song_limit")),
            float(redis.get("artist_limit")),
        )
        old_items = redis.zrangebyscore("play_queue", 0, time.time() - longest_limit)
        for item_id in old_items:
            redis.zrem("play_queue", item_id)
            redis.delete("item:"+item_id)
            redis.delete("item:"+item_id+":artists")

        if next_event is not None:

            print "PLANNING AHEAD."

            # Plan ahead

            print "EVENT:", next_event

            target_time = next_time.replace(
                hour=next_event.time.hour,
                minute=next_event.time.minute,
                second=next_event.time.second,
                microsecond=next_event.time.microsecond,
            )
            if target_time < next_time:
                target_time += timedelta(1)
            print "TARGET TIME:", target_time
            target_length = target_time - next_time
            print "TARGET LENGTH:", target_length

            candidates = []

            successful = False

            # Start by making 10 attempts...
            for n in range(10):
                attempt = plan_attempt(target_length, next_event.error_margin, next_time, cw, cw_items)
                if attempt["can_shorten"] or attempt["can_lengthen"]:
                    successful = True
                candidates.append(attempt)

            # ...and if that doesn't work, try another 100.
            if not successful:
                for n in range(100):
                    candidates.append(plan_attempt(target_length, next_event.error_margin, next_time, cw, cw_items))

            # Hopefully we should be able to find a successful plan in 10
            # attempts. For the particularly hard ones we can try 100, but
            # after that it's pretty unlikely that we can meet the target
            # time, so we just give up at that point.

            candidates.sort(key=lambda a: (
                0 if a["can_shorten"] or a["can_lengthen"] else 1,
                min(a["distance"], a["mls_distance"]),
            ))

            plan = candidates[0]

            for song in plan["songs"]:
                print song

            if plan["can_shorten"] and plan["can_lengthen"]:

                # Do whichever is closer.
                print "CAN SHORTEN OR LENGTHEN."
                print "SHORTEN DISTANCE:", plan["distance"]
                print "LENGTHEN DISTANCE:", plan["mls_distance"]

                if plan["distance"] < plan["mls_distance"]:
                    print "SHORTENING"
                    songs = shorten(
                        plan["songs"],
                        plan["distance"],
                        next_event.error_margin
                    )
                else:
                    print "LENGTHENING"
                    songs = lengthen(
                        plan["songs"][:-1],
                        plan["mls_distance"],
                        next_event.error_margin
                    )

            elif plan["can_shorten"]:

                # Shorten.
                print "CAN SHORTEN ONLY."
                print "SHORTEN DISTANCE:", plan["distance"]
                songs = shorten(
                    plan["songs"],
                    plan["distance"],
                    next_event.error_margin
                )

            elif plan["can_lengthen"]:

                # Lengthen.
                print "CAN LENGTHEN ONLY."
                print "LENGTHEN DISTANCE:", plan["mls_distance"]
                songs = lengthen(
                    plan["songs"][:-1],
                    plan["mls_distance"],
                    next_event.error_margin
                )

            else:

                # Do whichever is closer.
                print "NEITHER."

                print "SHORTEN DISTANCE:", plan["distance"]
                print "LENGTHEN DISTANCE:", plan["mls_distance"]

                if plan["distance"] < plan["mls_distance"]:
                    print "SHORTENING"
                    songs = plan["songs"]
                    for song in songs:
                        song[1] = song[0].min_length
                else:
                    print "LENGTHENING"
                    songs = plan["songs"][:-1]
                    for song in songs:
                        song[1] = song[0].max_length

            for song, length in songs:
                queue_song(next_time, song, length)
                next_time += length

            # Set current clockwheel to match the end of the plan.
            cw = plan["cw"]
            cw_items = plan["cw_items"]

            queue_event(next_time, next_event)
            if next_event.type == "stop":
                break

            next_time += next_event.length

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
        while (
            next_time-datetime.now() > timedelta(0, 1800)
            and redis.get("running") is not None
        ):
            redis.publish("update", "update")
            print "SLEEPING"
            time.sleep(300)

        # Check if we need a new clockwheel
        # or if the item list needs repopulating.
        new_cw = get_clockwheel(next_time)
        if new_cw != cw or len(cw_items) == 0:
            print "REFRESHING CLOCKWHEEL."
            cw = get_clockwheel(next_time)
            cw_items = populate_cw_items(cw)

        # Refresh the next event.
        next_event = find_event(next_time)

redis = StrictRedis()

redis.set("automation_pid", os.getpid())

# Set default values for repetition limits if they don't exist already.
if redis.get("song_limit") is None:
    redis.set("song_limit", 3600)
if redis.get("artist_limit") is None:
    redis.set("artist_limit", 3600)

# Make sure any existing future items are cleared.
future_items = redis.zrangebyscore("play_queue", time.time(), "inf")
for item_id in future_items:
    redis.zrem("play_queue", item_id)
    redis.delete("item:"+item_id)

redis.set("running", "True")

pq = Thread(target=play_queue)
pq.start()

try:
    scheduler()
    pq.join()
except:
    redis.delete("running")
    raise

redis.delete("running")
redis.delete("automation_pid")
