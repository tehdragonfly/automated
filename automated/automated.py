# cvlc -vvv -Idummy pulse:// --sout "#transcode{vcodec=none,acodec=vorbis,ab=128,channels=2,samplerate=44100}:http{mux=ogg,dst=:3837/}"

import os
import subprocess
import time

from datetime import datetime
from pydub import AudioSegment
from pydub.playback import play
from pydub.utils import get_player_name
from sqlalchemy import and_, func
from sqlalchemy.orm.exc import NoResultFound
from thread import start_new_thread

from db import Session, Category, Clockwheel, ClockwheelHour, ClockwheelItem, Play, Song

base_path = "songs/"

PLAYER = get_player_name()
FNULL = open(os.devnull, 'w')

def play_song(path):
    print "PLAYING", path
    #s = AudioSegment.from_file(base_path+path)
    #play(s)
    subprocess.call([PLAYER, "-nodisp", "-autoexit", base_path+path], stdout=FNULL, stderr=FNULL)

song_history = []

def get_clockwheel():
    now = datetime.now()
    try:
        return Session.query(Clockwheel).join(ClockwheelHour).filter(and_(
            ClockwheelHour.day==now.weekday(),
            ClockwheelHour.hour==now.hour,
        )).one()
    except NoResultFound:
        return None

def pick_song(category_id=None, use_history=True):
    song_query = Session.query(Song).order_by(func.random())
    if category_id is not None:
        song_query = song_query.filter(Song.category_id==category_id)
    if use_history and len(song_history)!=0:
        song_query = song_query.filter(~Song.id.in_(song_history))
    return song_query.first()

current_cw = get_clockwheel()
while True:
    print "STARTING LOOP. CURRENT CLOCKWHEEL IS", current_cw
    if current_cw is None:
        print "CLOCKWHEEL IS NONE, PICKING ANY SONG."
        song = pick_song()
        if song is None:
            print "NOTHING HERE, SKIPPING."
            continue
        print "SELECTED", song
        song_history.append(song.id)
        if len(song_history)>10:
            song_history.remove(song_history[0])
        start_new_thread(play_song, (song.filename,))
        Session.add(Play(time=datetime.now(), song=song, length=song.length))
        Session.commit()
        time.sleep(song.length.total_seconds())
        current_cw = get_clockwheel()
        continue
    for item, category in Session.query(ClockwheelItem, Category).join(Category).filter(
        ClockwheelItem.clockwheel==current_cw
    ).order_by(ClockwheelItem.number):
        print "ITEM", item
        print "CATEGORY", category
        if category.name=="Station ID":
            song = pick_song(category.id, False)
        else:
            # XXX HANDLE SONG BEING NONE
            song = pick_song(category.id)
            if song is None:
                print "NOTHING HERE, SKIPPING."
                continue
            print "SELECTED", song
            song_history.append(song.id)
            if len(song_history)>10:
                song_history.remove(song_history[0])
        start_new_thread(play_song, (song.filename,))
        Session.add(Play(time=datetime.now(), song=song, length=song.length))
        Session.commit()
        time.sleep(song.length.total_seconds())
        new_cw = get_clockwheel()
        # If the current clockwheel has changed, cut the loop short and move on to the new clockwheel.
        if new_cw!=current_cw:
            print "CLOCKWHEEL CHANGED, BREAKING."
            current_cw = new_cw
            break

