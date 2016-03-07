import time

from datetime import datetime, timedelta
from redis import StrictRedis
from sqlalchemy import and_, func, or_
from sqlalchemy.orm.exc import NoResultFound

from automated.db import (
    Session,
    Artist,
    Category,
    Event,
    ScheduleHour,
    Sequence,
    SequenceItem,
    Song,
)

redis = StrictRedis()


def find_event(last_event, range_start):
    event_query = Session.query(Event)
    if last_event:
        event_query = event_query.filter(Event.time > last_event.time)
    else:
        event_query = event_query.filter(Event.time > range_start)
    range_end = range_start + timedelta(0, 3600)
    event_query = event_query.filter(Event.time <= range_end)
    event_query = event_query.order_by(Event.time)
    return event_query.first()


def get_sequence(target_time):
    if target_time is None:
        target_time = datetime.now()
    try:
        return Session.query(Sequence).join(ScheduleHour).filter(and_(
            ScheduleHour.day == target_time.weekday(),
            ScheduleHour.hour == target_time.hour,
        )).one()
    except NoResultFound:
        return None


def populate_sequence_items(sequence):
    return Session.query(SequenceItem, Category).join(Category).filter(
        SequenceItem.sequence == sequence
    ).order_by(SequenceItem.number).all() if sequence is not None else []


def pick_song(queue_time, category_id=None, songs=None, artists=None, length=None):

    song_query = Session.query(Song).order_by(func.random())

    if category_id is not None:
        song_query = song_query.filter(Song.category_id == category_id)

    queue_timestamp = time.mktime(queue_time.timetuple())

    # Song limit
    song_timestamp = queue_timestamp - float(redis.get("song_limit"))
    if songs is None:
        songs = set()
    for item_id in redis.zrangebyscore("play_queue", song_timestamp, queue_timestamp):
        song_id = redis.hget("item:"+item_id, "song_id")
        if song_id is not None:
            songs.add(song_id)
    if len(songs) != 0:
        song_query = song_query.filter(~Song.id.in_(songs))

    # Artist limit
    artist_timestamp = queue_timestamp - float(redis.get("artist_limit"))
    if artists is None:
        artists = set()
    for item_id in redis.zrangebyscore("play_queue", artist_timestamp, queue_timestamp):
        artists = artists | redis.smembers("item:"+item_id+":artists")
    if len(artists) != 0:
        song_query = song_query.filter(~Song.artists.any(Artist.id.in_(artists)))

    if length is not None:
        length_song = song_query.filter(and_(
            Song.min_end-Song.start <= length,
            Song.max_end-Song.start >= length,
        )).first()
        if length_song is not None:
            return length_song

    return song_query.first()
