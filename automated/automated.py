import os
import subprocess
import time

from datetime import datetime, timedelta
from pydub.utils import get_player_name
from redis import StrictRedis
from sqlalchemy import and_, func
from sqlalchemy.orm.exc import NoResultFound
from threading import Thread
from uuid import uuid4

from db import Session, Category, Clockwheel, ClockwheelHour, ClockwheelItem, Play, Song

redis = StrictRedis()
redis.flushall()

base_path = "songs/"

PLAYER = get_player_name()
FNULL = open(os.devnull, 'w')

def play_song(item_id, item):
    #print "PLAYING", item
    redis.hset("item:"+item_id, "status", "playing")
    subprocess.call([PLAYER, "-nodisp", "-autoexit", base_path+item["filename"]], stdout=FNULL, stderr=FNULL)
    redis.hset("item:"+item_id, "status", "played")

def play_queue():
    while running:
        t = time.time()
        result = redis.zrangebyscore("play_queue", t-1, t)
        #print t, result
        for item_id in result:
            item = redis.hgetall("item:"+item_id)
            if len(item)==0:
                redis.zrem("play_queue", item_id, item)
                continue
            if item["status"] != "queued":
                continue
            Thread(target=play_song, args=(item_id, item)).start()
        time.sleep(0.01)

def get_clockwheel(target_time):
    if target_time is None:
        target_time = datetime.now()
    try:
        return Session.query(Clockwheel).join(ClockwheelHour).filter(and_(
            ClockwheelHour.day==target_time.weekday(),
            ClockwheelHour.hour==target_time.hour,
        )).one()
    except NoResultFound:
        return None

def pick_song(category_id=None):
    song_query = Session.query(Song).order_by(func.random())
    if category_id is not None:
        song_query = song_query.filter(Song.category_id==category_id)
    return song_query.first()

def queue_song(queue_time, song):
    queue_item_id = str(uuid4())
    redis.hmset("item:"+queue_item_id, {
        "status": "queued",
        "song_id": song.id,
        "length": song.length.total_seconds(),
        "filename": song.filename,
    })
    redis.zadd("play_queue", time.mktime(queue_time.timetuple()), queue_item_id)

def scheduler():
    next_time = datetime.fromtimestamp(round(time.time()+3))
    current_cw = get_clockwheel(next_time)
    while True:
        print "STARTING LOOP. CURRENT CLOCKWHEEL IS", current_cw
        if current_cw is None:
            print "CLOCKWHEEL IS NONE, PICKING ANY SONG."
            song = pick_song()
            if song is None:
                print "NOTHING HERE, SKIPPING."
                continue
            print "SELECTED", song
            queue_song(next_time, song)
            # Pause if we've reached more than 30 minutes into the future.
            while next_time-datetime.now() > timedelta(0, 1800):
                print "SLEEPING"
                time.sleep(300)
            current_cw = get_clockwheel(next_time)
        for item, category in Session.query(ClockwheelItem, Category).join(Category).filter(
            ClockwheelItem.clockwheel==current_cw
        ).order_by(ClockwheelItem.number):
            print "ITEM", item
            print "CATEGORY", category
            song = pick_song(category.id)
            if song is None:
                print "NOTHING HERE, SKIPPING."
                continue
            print "SELECTED", song
            queue_song(next_time, song)
            next_time += song.length
            # Pause if we've reached more than 30 minutes into the future.
            while next_time-datetime.now() > timedelta(0, 1800):
                print "SLEEPING"
                time.sleep(300)
            # Get new clockwheel, skipping the rest of this one if it's changed.
            new_cw = get_clockwheel(next_time)
            if new_cw!=current_cw:
                print "CLOCKWHEEL CHANGED, BREAKING."
                current_cw = new_cw
                break

running = True

Thread(target=play_queue).start()

try:
    scheduler()
except:
    running = False
    raise

