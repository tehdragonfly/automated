import asyncio, os, subprocess, time, vlc

from datetime import datetime, timedelta
from pydub.utils import get_player_name
from redis import StrictRedis
from uuid import uuid4

from automated.db import Session, Play


redis = StrictRedis(decode_responses=True)


# TODO config
PATHS = {
    "song": "songs/",
    "audio": "events/",
}


async def play_item(queue_time, item_id, item):
    # TODO redis shit

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

    for next_keyframe in keyframes:
        while True:
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
            print(new_volume)
            mp.audio_set_volume(new_volume)
            await asyncio.sleep(0.01)
        previous_keyframe = next_keyframe

    mp.stop()
    mp.release()
    print("end")


PLAYER = get_player_name()
FNULL = open(os.devnull, 'w')


def old_play_song(queue_time, item_id, item):

    if item["type"] == "song":
        filename = PATHS["song"] + item["filename"]
    elif item["type"] == "audio":
        filename = PATHS["audio"] + item["filename"]

    # Calculate how early we're meant to start the item and wait until then.
    play_time = queue_time - float(item.get("start", 0))
    wait = play_time - time.time()
    if wait > 0:
        time.sleep(wait)

    if item["type"] == "song":
        Session.add(Play(
            time=datetime.now(),
            song_id=int(item["song_id"]),
            length=timedelta(0, float(item["length"]))
        ))
        Session.commit()
    elif item["type"] == "stop":
        redis.hset("item:"+item_id, "status", "played")
        redis.publish("update", "update")
        redis.delete("running")
        redis.delete("automation_pid")
        return

    redis.hset("item:"+item_id, "status", "playing")
    redis.publish("update", "update")

    subprocess.call(
        [PLAYER, "-nodisp", "-autoexit", filename],
        stdout=FNULL, stderr=FNULL,
    )
    redis.hset("item:"+item_id, "status", "played")
    redis.publish("update", "update")

    if redis.get("running") is None:
        redis.delete("automation_pid")


def queue_song(queue_time, song, force_length=None):
    queue_item_id = str(uuid4())
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
    redis.hmset("item:"+queue_item_id, item_info)
    if song.artists:
        redis.sadd("item:"+queue_item_id+":artists", *(_.id for _ in song.artists))
    queue_timestamp = time.mktime(queue_time.timetuple()) + queue_time.microsecond/1000000.0
    redis.zadd("play_queue", queue_timestamp, queue_item_id)


def queue_stop(queue_time, event):
    queue_item_id = str(uuid4())
    item_info = {
        "status": "queued",
        "type": "stop",
        "event_id": event.id,
    }
    redis.hmset("item:"+queue_item_id, item_info)
    queue_timestamp = time.mktime(queue_time.timetuple()) + queue_time.microsecond/1000000.0
    redis.zadd("play_queue", queue_timestamp, queue_item_id)


def queue_event_item(queue_time, event_item):
    if event_item.type == "song":
        return queue_song(queue_time, event_item.song)
    queue_item_id = str(uuid4())
    item_info = {
        "status": "queued",
        "type": "audio",
        "start": 0,
        "length": event_item.length.total_seconds(),
        "event_item_id": event_item.id,
        "filename": str(event_item.id),
    }
    redis.hmset("item:"+queue_item_id, item_info)
    queue_timestamp = time.mktime(queue_time.timetuple()) + queue_time.microsecond/1000000.0
    redis.zadd("play_queue", queue_timestamp, queue_item_id)

