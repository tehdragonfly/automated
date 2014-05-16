import os
import subprocess
import time

from datetime import datetime, timedelta
from pydub.utils import get_player_name
from redis import StrictRedis
from uuid import uuid4

from automated.db import Session, Play

redis = StrictRedis()

PLAYER = get_player_name()
FNULL = open(os.devnull, 'w')


def play_song(queue_time, item_id, item):

    if item["type"] == "song":
        filename = "songs/" + item["filename"]
    elif item["type"] == "audio":
        filename = "events/" + item["filename"]

    # Calculate how early we're meant to start the item and wait until then.
    play_time = queue_time - float(item.get("start", 0))
    time.sleep(play_time - time.time())

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

    subprocess.call([PLAYER, "-nodisp", "-autoexit", filename], stdout=FNULL, stderr=FNULL)
    redis.hset("item:"+item_id, "status", "played")
    redis.publish("update", "update")

    if redis.get("running") is None:
        redis.delete("automation_pid")


def queue_song(queue_time, song, force_length=None):
    queue_item_id = str(uuid4())
    item_info = {
        "status": "queued",
        "type": "song",
        "song_id": song.id,
        "start": song.start.total_seconds(),
        "length": force_length.total_seconds() or song.length.total_seconds(),
        "normal_length": song.length.total_seconds(),
        "filename": song.filename,
    }
    if song.album is not None:
        item_info["album"] = song.album
    redis.hmset("item:"+queue_item_id, item_info)
    redis.sadd("item:"+queue_item_id+":artists", *(_.id for _ in song.artists))
    redis.zadd("play_queue", time.mktime(queue_time.timetuple()), queue_item_id)


def queue_event(queue_time, event):
    queue_item_id = str(uuid4())
    item_info = {
        "status": "queued",
        "type": event.type,
        "event_id": event.id,
        "filename": event.filename,
    }
    if event.length is not None:
        item_info["length"] = event.length.total_seconds()
    redis.hmset("item:"+queue_item_id, item_info)
    redis.zadd("play_queue", time.mktime(queue_time.timetuple()), queue_item_id)


