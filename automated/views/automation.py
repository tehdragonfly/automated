import time

from datetime import datetime, timedelta
from flask import abort, jsonify, redirect, render_template, request, url_for
from redis import StrictRedis
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import NoResultFound

from automated.db import Session, Song, WeeklyEvent

redis = StrictRedis()

def automation():
    alive = redis.get("automation_pid") is not None
    running = redis.get("running") is not None
    play_queue = []
    for item_id, timestamp in redis.zrange("play_queue", 0, -1, withscores=True):
        item = redis.hgetall("item:"+item_id)
        if "length" in item:
            item["length"] = timedelta(0, float(item["length"]))
        song = None
        if item["type"] == "song":
            song = Session.query(Song).filter(
                Song.id==int(item["song_id"])
            ).options(
                joinedload(Song.artists),
                joinedload(Song.category),
            ).one()
        else:
            event = Session.query(WeeklyEvent).filter(
                WeeklyEvent.id==int(item["event_id"]),
            ).one()
        play_queue.append((datetime.fromtimestamp(timestamp), item, song or event))
    return render_template(
        "automation.html",
        section="automation",
        alive=alive,
        running=running,
        play_queue=play_queue,
    )


def update():
    ps = redis.pubsub()
    ps.subscribe("update")
    for m in ps.listen():
        if m["type"] == "message":
            break
    play_queue = []
    for item_id, timestamp in redis.zrange("play_queue", 0, -1, withscores=True):
        item = redis.hgetall("item:"+item_id)
        item_dict = {
            "status": item["status"],
            "time": datetime.fromtimestamp(timestamp).strftime("%H:%M:%S"),
        }
        if "length" in item:
            item_dict["length"] = str(timedelta(0, float(item["length"])))
        if item["type"] == "song":
            song = Session.query(Song).filter(
                Song.id==int(item["song_id"])
            ).options(
                joinedload(Song.artists),
                joinedload(Song.category),
            ).one()
            item_dict["name"] = song.name
            item_dict["artist"] = ""
            if song.artists:
                item_dict["artist"] += "Artist: "
                for artist in song.artists:
                    item_dict["artist"] += artist.name + ", "
            item_dict["artist"] += "Category: " + song.category.name
        else:
            event = Session.query(WeeklyEvent).filter(
                WeeklyEvent.id==int(item["event_id"]),
            ).one()
            item_dict["name"] = event.name
            item_dict["artist"] = event.type + " event"
        play_queue.append(item_dict)
    return jsonify({ "play_queue": play_queue })

