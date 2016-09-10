import asyncio
import os
import time

from datetime import datetime, timedelta
from redis import StrictRedis
from threading import Thread

from automated.db import Session, Category, Sequence, SequenceItem
from automated.helpers.plan import plan_attempt, shorten, lengthen
from automated.helpers.play import play_item, old_play_song, queue_song, queue_stop, queue_event_item
from automated.helpers.schedule import find_event, populate_sequence_items, pick_song


async def play_queue():
    while redis.get("running") is not None:
        t = time.time()
        # Cue things up 10 seconds ahead.
        play_items = redis.zrangebyscore("play_queue", t-1, t+10, withscores=True)
        for item_id, queue_time in play_items:
            item = redis.hgetall("item:"+item_id)
            if len(item) == 0:
                redis.zrem("play_queue", item_id, item)
                continue
            if item["status"] != "queued":
                continue
            redis.hset("item:"+item_id, "status", "preparing")
            if item["type"] != "stop":
                loop.create_task(play_item(queue_time, item_id, item))
            else:
                Thread(target=old_play_song, args=(queue_time, item_id, item)).start()
        await asyncio.sleep(0.01)


async def scheduler():

    next_time = datetime.now() + timedelta(0, 5)
    last_event = None
    next_event = None
    # TODO get sequence from stream
    sequence = None
    sequence_items = populate_sequence_items(sequence)

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

            print("PLANNING AHEAD.")

            # Plan ahead

            print("EVENT:", next_event)

            if next_event.start_time > next_time:

                print("TARGET TIME:", next_event.start_time)
                target_length = next_event.start_time - next_time
                print("TARGET LENGTH:", target_length)

                candidates = []

                successful = False

                # Start by making 10 attempts...
                for n in range(10):
                    attempt = plan_attempt(target_length, next_event.error_margin, next_time, sequence, sequence_items)
                    if attempt["can_shorten"] or attempt["can_lengthen"]:
                        successful = True
                    candidates.append(attempt)

                # ...and if that doesn't work, try another 100.
                if not successful:
                    for n in range(100):
                        candidates.append(plan_attempt(target_length, next_event.error_margin, next_time, sequence, sequence_items))

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
                    print(song)

                if plan["can_shorten"] and plan["can_lengthen"]:

                    # Do whichever is closer.
                    print("CAN SHORTEN OR LENGTHEN.")
                    print("SHORTEN DISTANCE:", plan["distance"])
                    print("LENGTHEN DISTANCE:", plan["mls_distance"])

                    if plan["distance"] < plan["mls_distance"]:
                        print("SHORTENING")
                        songs = shorten(
                            plan["songs"],
                            plan["distance"],
                            next_event.error_margin
                        )
                    else:
                        print("LENGTHENING")
                        songs = lengthen(
                            plan["songs"][:-1],
                            plan["mls_distance"],
                            next_event.error_margin
                        )

                elif plan["can_shorten"]:

                    # Shorten.
                    print("CAN SHORTEN ONLY.")
                    print("SHORTEN DISTANCE:", plan["distance"])
                    songs = shorten(
                        plan["songs"],
                        plan["distance"],
                        next_event.error_margin
                    )

                elif plan["can_lengthen"]:

                    # Lengthen.
                    print("CAN LENGTHEN ONLY.")
                    print("LENGTHEN DISTANCE:", plan["mls_distance"])
                    songs = lengthen(
                        plan["songs"][:-1],
                        plan["mls_distance"],
                        next_event.error_margin
                    )

                else:

                    # Do whichever is closer.
                    print("NEITHER.")

                    print("SHORTEN DISTANCE:", plan["distance"])
                    print("LENGTHEN DISTANCE:", plan["mls_distance"])

                    if plan["distance"] < plan["mls_distance"]:
                        print("SHORTENING")
                        songs = plan["songs"]
                        for song in songs:
                            song[1] = song[0].min_length
                    else:
                        print("LENGTHENING")
                        songs = plan["songs"][:-1]
                        for song in songs:
                            song[1] = song[0].max_length

                for song, length in songs:
                    queue_song(next_time, song, length)
                    next_time += length

                # Set current sequence to match the end of the plan.
                sequence = plan["sequence"]
                sequence_items = plan["sequence_items"]

            else:
                print("EVENT TIME IN THE PAST, PLAYING IMMEDIATELY")

            if next_event.type == "stop":
                queue_stop(next_time, next_event)

            for event_item in next_event.items:
                print("EVENT ITEM:", event_item)
                queue_event_item(next_time, event_item)
                next_time += event_item.length

        else:

            print("IMPROVISING.")

            # Improvise

            if sequence is None or len(sequence_items) == 0:

                # If there isn't a sequence, just pick any song.
                print("SEQUENCE IS NONE, PICKING ANY SONG.")
                song = pick_song(next_time or datetime.now())

            else:

                # Otherwise pick songs from the sequence.
                print("CURRENT SEQUENCE IS", sequence)
                item, category = sequence_items.pop(0)
                print("ITEM", item)
                print("CATEGORY", category)
                song = pick_song(next_time or datetime.now(), category.id)

            # Skip if we can't find a song.
            # This allows us to move on if one category in the sequence is
            # exhausted, although it risks putting us into an infinite loop
            # if there aren't enough songs in the other categories.
            if song is not None:
                queue_song(next_time, song)
                next_time += song.length
                print("SELECTED", song)
            else:
                print("NOTHING HERE, SKIPPING.")

        # Pause if we've reached more than 30 minutes into the future.
        while (
            next_time-datetime.now() > timedelta(0, 1800)
            and redis.get("running") is not None
        ):
            redis.publish("update", "update")
            print("SLEEPING")
            await asyncio.sleep(300)

        # Check if we need a new sequence
        # or if the item list needs repopulating.
        # TODO get sequence from stream
        new_sequence = None
        if new_sequence != sequence or len(sequence_items) == 0:
            print("REFRESHING SEQUENCE.")
            sequence = None
            sequence_items = populate_sequence_items(sequence)

        # Refresh the next event.
        if next_event is not None:
            last_event = next_event
        next_event = find_event(last_event, next_time)

redis = StrictRedis(decode_responses=True)

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

loop = asyncio.get_event_loop()

try:
    loop.create_task(play_queue())
    loop.create_task(scheduler())
    loop.run_forever()
except:
    redis.delete("running")
    raise

redis.delete("running")
redis.delete("automation_pid")

