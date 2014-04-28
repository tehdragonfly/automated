from collections import defaultdict
from flask import Flask, abort, redirect, render_template, request, url_for
from sqlalchemy import and_
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import NoResultFound

from db import Session, Category, Clockwheel, ClockwheelHour, ClockwheelItem, Song
from views import schedule, playlist

app = Flask(__name__)

@app.after_request
def shutdown_session(response=None):
    Session.commit()
    return response

@app.teardown_request
def shutdown_session(exception=None):
    Session.remove()

# Schedule

app.add_url_rule("/schedule", "schedule", schedule.schedule, methods=("GET",))
app.add_url_rule("/schedule/edit", "edit_schedule", schedule.edit_schedule, methods=("POST",))
app.add_url_rule("/schedule/clockwheel/new", "new_clockwheel", schedule.new_clockwheel, methods=("POST",))
app.add_url_rule("/schedule/clockwheel/<int:clockwheel_id>", "clockwheel", schedule.clockwheel, methods=("GET",))
app.add_url_rule("/schedule/clockwheel/<int:clockwheel_id>/add_item", "add_clockwheel_item", schedule.add_clockwheel_item, methods=("POST",))
app.add_url_rule("/schedule/clockwheel/<int:clockwheel_id>/remove_item", "remove_clockwheel_item", schedule.remove_clockwheel_item, methods=("POST",))

# Playlist

app.add_url_rule("/playlist", "playlist", playlist.playlist, methods=("GET",))
app.add_url_rule("/playlist/category/new", "new_category", playlist.new_category, methods=("POST",))
app.add_url_rule("/playlist/category/<int:category_id>", "playlist", playlist.playlist, methods=("GET",))
app.add_url_rule("/playlist/song/new", "new_song", playlist.new_song, methods=("POST",))
app.add_url_rule("/playlist/song/<int:song_id>", "song", playlist.song, methods=("GET",))
app.add_url_rule("/playlist/song/<int:song_id>/edit", "edit_song", playlist.edit_song, methods=("POST",))

