import asyncio, aioredis, subprocess, time, vlc

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from uuid import uuid4

from automated.db import sm, Play, Stream
from automated.helpers.args import args


loop = asyncio.get_event_loop()
redis = loop.run_until_complete(aioredis.create_redis(("127.0.0.1", 6379), encoding="utf-8"))

executor = ThreadPoolExecutor()


PATHS = {
    "song": (args.song_path or "songs") + "/",
    "audio": (args.audio_path or "events") + "/",
}


async def play_item(queue_time, item_id, item):
    keyframes = []
    if float(item["start"]) >= 2:
        keyframes.append((queue_time - 2, 40))
    keyframes += [
        (queue_time, 100),
        (queue_time + float(item["length"]), 100),
        (queue_time + float(item["length"]) + 5, 0),
    ]

    mp = vlc.MediaPlayer(PATHS[item["type"]] + item["filename"])

    mp.audio_set_volume(0)
    mp.play()
    while mp.get_state() in (vlc.State.NothingSpecial, vlc.State.Opening, vlc.State.Buffering):
        await asyncio.sleep(0.01)
    mp.pause()

    play_time = queue_time - float(item["start"])
    time_difference = play_time - time.time()
    if time_difference >= 0:
        print("future", time_difference)
        # Future: start at the beginning with default volume.
        mp.set_time(0)
        previous_keyframe = (play_time, keyframes[0][1])
        mp.audio_set_volume(keyframes[0][1])
        await asyncio.sleep(time_difference)
    elif time_difference < 0:
        print("past", -int(time_difference * 1000))
        # Past: skip to time and fade in.
        mp.set_time(-int(time_difference * 1000))
        previous_keyframe = (time.time(), 0)

    mp.play()

    # Don't await because we don't care about the response.
    loop.create_task(update_item_status(item_id, "playing"))

    logged = False

    for next_keyframe in keyframes:
        if item["type"] == "song" and not logged and previous_keyframe[0] == queue_time:
            executor.submit(log_song, item["song_id"], item["length"])
            logged = True

        while mp.get_state() != vlc.State.Ended:
            current_time = time.time()
            if previous_keyframe[1] == next_keyframe[1] and next_keyframe[0] - current_time > 1:
                await asyncio.sleep(1)
                continue
            if current_time > next_keyframe[0]:
                print("reached keyframe", next_keyframe)
                mp.audio_set_volume(next_keyframe[1])
                break
            new_volume = previous_keyframe[1] + int(
                (current_time - previous_keyframe[0])
                / (next_keyframe[0] - previous_keyframe[0])
                * (next_keyframe[1] - previous_keyframe[1])
            )
            mp.audio_set_volume(new_volume)
            await asyncio.sleep(0.01)

        previous_keyframe = next_keyframe

    print("ended")
    loop.create_task(update_item_status(item_id, "played"))

    if await redis.get("running") is None:
        await redis.delete("automation_pid")

    mp.stop()
    mp.release()
    print("end")


async def stop_item(queue_time, item_id, item):
    time_difference = queue_time - time.time()
    if time_difference >= 0:
        await asyncio.sleep(time_difference)

    await redis.hset("item:" + item_id, "status", "played")
    await redis.publish("update", "update")
    await redis.delete("running")
    await redis.delete("automation_pid")


async def update_item_status(item_id, status):
    await redis.hset("item:" + item_id, "status", "playing")
    await redis.publish("update", "update")


def log_song(song_id, length):
    db = sm()
    db.add(Play(
        stream_id=db.query(Stream.id).filter(Stream.url_name == args.stream).as_scalar(),
        time=datetime.now(),
        song_id=int(song_id),
        length=timedelta(0, float(length)),
    ))
    db.commit()


async def _queue(queue_time, item_info):
    queue_item_id = str(uuid4())
    await redis.hmset_dict("item:" + queue_item_id, item_info)
    queue_timestamp = time.mktime(queue_time.timetuple()) + queue_time.microsecond / 1000000.0
    await redis.zadd("play_queue", queue_timestamp, queue_item_id)
    return queue_item_id


async def queue_song(queue_time, song, force_length=None):
    item_info = {
        "status": "queued",
        "type": "song",
        "start": song.start.total_seconds(),
        "length": (
            force_length.total_seconds() if force_length is not None
            else song.length.total_seconds()
        ),
        "song_id": song.id,
        "filename": song.filename,
    }
    queue_item_id = await _queue(queue_time, item_info)
    if song.artists:
        await redis.sadd("item:" + queue_item_id + ":artists", *(_.id for _ in song.artists))
    return queue_item_id


async def queue_stop(queue_time, event):
    queue_item_id = str(uuid4())
    return await _queue(queue_time, {
        "status": "queued",
        "type": "stop",
        "event_id": event.id,
    })


async def queue_event_start(queue_time, event):
    pass


async def queue_event_item(queue_time, event_item):
    if event_item.type == "song":
        return await queue_song(queue_time, event_item.song)
    return await _queue(queue_time, {
        "status": "queued",
        "type": "audio",
        "start": event_item.start.total_seconds(),
        "length": event_item.length.total_seconds(),
        "event_item_id": event_item.id,
        "filename": str(event_item.id),
    })


async def queue_event_end(queue_time, event):
    pass

