import asyncio
import aioredis
import os
import time

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from automated.helpers.plan import plan_attempt, shorten, lengthen
from automated.helpers.play import play_item, stop_item, queue_song, queue_stop, queue_event_item
from automated.helpers.schedule import find_event, populate_sequence_items, pick_song


loop = asyncio.get_event_loop()
redis = loop.run_until_complete(aioredis.create_redis(("127.0.0.1", 6379), encoding="utf-8"))

executor = ThreadPoolExecutor()


async def setup():
    await redis.set("automation_pid", os.getpid())

    # Set default values for repetition limits if they don't exist already.
    if await redis.get("song_limit") is None:
        await redis.set("song_limit", 3600)
    if await redis.get("artist_limit") is None:
        await redis.set("artist_limit", 3600)

    # Make sure any existing future items are cleared.
    future_items = await redis.zrangebyscore("play_queue", time.time(), float("inf"))
    for item_id in future_items:
        await redis.zrem("play_queue", item_id)
        await redis.delete("item:"+item_id)

    await redis.set("running", "True")


def split_zitems(zitems):
    i = iter(zitems)
    return zip(i, i)


async def play_queue():
    while await redis.get("running") is not None:
        t = time.time()
        # Cue things up 10 seconds ahead.
        play_items = split_zitems(await redis.zrangebyscore("play_queue", t - 1, t + 10, withscores=True))
        for item_id, queue_time in play_items:
            item = await redis.hgetall("item:" + item_id)
            if len(item) == 0:
                await redis.zrem("play_queue", item_id, item)
                continue
            if item["status"] != "queued":
                continue
            await redis.hset("item:" + item_id, "status", "preparing")
            if item["type"] != "stop":
                loop.create_task(play_item(queue_time, item_id, item))
            else:
                loop.create_task(stop_item(queue_time, item_id, item))
        await asyncio.sleep(0.01)


async def scheduler():

    next_time      = datetime.now() + timedelta(0, 5)
    current_event  = None
    next_event     = None
    # TODO get sequence from stream
    sequence       = None
    sequence_items = await loop.run_in_executor(executor, populate_sequence_items, sequence)

    while await redis.get("running") is not None:

        # Trim playlist items older than the longest repetition limit.
        longest_limit = max(
            float(await redis.get("song_limit")),
            float(await redis.get("artist_limit")),
        )
        old_items = await redis.zrangebyscore("play_queue", 0, time.time() - longest_limit)
        for item_id in old_items:
            await redis.zrem("play_queue", item_id)
            await redis.delete("item:" + item_id)
            await redis.delete("item:" + item_id + ":artists")

        if next_event is not None:

            print("PLANNING AHEAD.")

            # Plan ahead

            print("EVENT:", next_event)

            if next_event.start_time > next_time:

                print("TARGET TIME:", next_event.start_time)
                target_length = next_event.start_time - next_time
                print("TARGET LENGTH:", target_length)

                # Start by making 10 attempts...
                attempts, errors = await asyncio.wait([
                    plan_attempt(target_length, next_event.error_margin, next_time, sequence, sequence_items, current_event.end_time)
                    for n in range(10)
                ])
                candidates = [_.result() for _ in attempts]
                # TODO do something with errors

                # ...and if that didn't give us any good plans, try another 100.
                if not any(attempt["can_shorten"] or attempt["can_lengthen"] for attempt in candidates):
                    attempts, errors = await asyncio.wait([
                        plan_attempt(target_length, next_event.error_margin, next_time, sequence, sequence_items, current_event.end_time)
                        for n in range(10)
                    ])
                    candidates += [_.result() for _ in attempts]
                    # TODO do something with errors

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
                    await queue_song(next_time, song, length)
                    next_time += length

                # Set current sequence to match the end of the plan.
                sequence = plan["sequence"]
                sequence_items = plan["sequence_items"]

            else:
                print("EVENT TIME IN THE PAST, PLAYING IMMEDIATELY")

            if next_event.type == "stop":
                await queue_stop(next_time, next_event)

            else:
                current_event, next_event = next_event, None

                # Set current sequence based on the current event.
                if current_event.sequence and current_event.sequence != sequence:
                    print("USING EVENT SEQUENCE:", current_event.sequence)
                    sequence = current_event.sequence
                    sequence_items = await loop.run_in_executor(executor, populate_sequence_items, sequence)

                for event_item in current_event.items:
                    print("EVENT ITEM:", event_item)
                    await queue_event_item(next_time, event_item)
                    next_time += event_item.length

        else:

            print("IMPROVISING.")

            # Improvise

            if sequence is None or len(sequence_items) == 0:

                # If there isn't a sequence, just pick any song.
                print("SEQUENCE IS NONE, PICKING ANY SONG.")
                song = await loop.run_in_executor(executor, pick_song, next_time or datetime.now())

            else:

                # Otherwise pick songs from the sequence.
                print("CURRENT SEQUENCE IS", sequence)
                item, category = sequence_items.pop(0)
                print("ITEM", item)
                print("CATEGORY", category)
                song = await loop.run_in_executor(executor, pick_song, next_time or datetime.now(), category.id)

            # Skip if we can't find a song.
            # This allows us to move on if one category in the sequence is
            # exhausted, although it risks putting us into an infinite loop
            # if there aren't enough songs in the other categories.
            if song is not None:
                await queue_song(next_time, song)
                next_time += song.length
                print("SELECTED", song)
            else:
                print("NOTHING HERE, SKIPPING.")

        # Pause if we've reached more than 30 minutes into the future.
        while (
            next_time - datetime.now() > timedelta(0, 1800)
            and await redis.get("running") is not None
        ):
            await redis.publish("update", "update")
            print("SLEEPING")
            await asyncio.sleep(300)

        # Reset the sequence if the current event is over.
        if current_event and current_event.end_time and next_time > current_event.end_time:
            print("EVENT OVER, RESETTING SEQUENCE")
            current_event = None
            # TODO get default sequence from stream
            sequence = None
            sequence_items = await loop.run_in_executor(executor, populate_sequence_items, sequence)

        # Or just check if the item list needs repopulating.
        elif len(sequence_items) == 0:
            print("REPOPULATING SEQUENCE_ITEMS")
            sequence_items = await loop.run_in_executor(executor, populate_sequence_items, sequence)

        next_event = await loop.run_in_executor(executor, find_event, current_event, next_time)


try:
    loop.run_until_complete(setup())
    loop.create_task(play_queue())
    loop.create_task(scheduler())
    loop.run_forever()
except:
    loop.run_until_complete(redis.delete("running"))
    raise

loop.run_until_complete(redis.delete("running"))
loop.run_until_complete(redis.delete("automation_pid"))

