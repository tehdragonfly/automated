from collections import defaultdict
from flask import Flask, abort, redirect, render_template, request, url_for
from sqlalchemy import and_
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import NoResultFound

from db import Session, Category, Clockwheel, ClockwheelHour, ClockwheelItem, Song
from views import automation, schedule, playlist

app = Flask(__name__)

@app.after_request
def shutdown_session(response=None):
    Session.commit()
    return response

@app.teardown_request
def shutdown_session(exception=None):
    Session.remove()

# Automate

app.add_url_rule("/", "automation", automation.automation, methods=("GET",))

# Schedule

app.add_url_rule("/schedule", "schedule", schedule.schedule, methods=("GET",))
app.add_url_rule("/schedule/edit", "edit_schedule", schedule.edit_schedule, methods=("POST",))

app.add_url_rule("/schedule/clockwheels/new", "new_clockwheel", schedule.new_clockwheel, methods=("POST",))
app.add_url_rule("/schedule/clockwheels/<int:clockwheel_id>", "clockwheel", schedule.clockwheel, methods=("GET",))
app.add_url_rule("/schedule/clockwheels/<int:clockwheel_id>/add_item", "add_clockwheel_item", schedule.add_clockwheel_item, methods=("POST",))
app.add_url_rule("/schedule/clockwheels/<int:clockwheel_id>/remove_item", "remove_clockwheel_item", schedule.remove_clockwheel_item, methods=("POST",))

app.add_url_rule("/schedule/events", "event_list", schedule.event_list, methods=("GET",))
app.add_url_rule("/schedule/events/new", "new_event", schedule.new_event, methods=("POST",))
app.add_url_rule("/schedule/events/<int:event_id>/delete", "delete_event", schedule.delete_event, methods=("POST",))

# Playlist

app.add_url_rule("/playlist", "playlist", playlist.playlist, methods=("GET",))
app.add_url_rule("/playlist/categories/new", "new_category", playlist.new_category, methods=("POST",))
app.add_url_rule("/playlist/categories/<int:category_id>", "playlist", playlist.playlist, methods=("GET",))
app.add_url_rule("/playlist/songs/new", "new_song", playlist.new_song, methods=("POST",))
app.add_url_rule("/playlist/songs/<int:song_id>", "song", playlist.song, methods=("GET",))
app.add_url_rule("/playlist/songs/<int:song_id>/edit", "edit_song", playlist.edit_song, methods=("POST",))

