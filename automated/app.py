from collections import defaultdict
from flask import Flask, abort, redirect, render_template, request, url_for
from sqlalchemy import and_
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import NoResultFound

from automated.db import Session
from automated.views import automation, schedule, playlist, log

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
app.add_url_rule("/update", "automation_update", automation.update, methods=("GET",))

# Schedule

app.add_url_rule("/schedule", "schedule", schedule.schedule, methods=("GET",))
app.add_url_rule("/schedule/edit", "edit_schedule", schedule.edit_schedule, methods=("POST",))

app.add_url_rule("/schedule/sequences/new", "new_sequence", schedule.new_sequence, methods=("POST",))
app.add_url_rule("/schedule/sequences/<int:sequence_id>", "sequence", schedule.sequence, methods=("GET",))
app.add_url_rule("/schedule/sequences/<int:sequence_id>/add_item", "add_sequence_item", schedule.add_sequence_item, methods=("POST",))
app.add_url_rule("/schedule/sequences/<int:sequence_id>/remove_item", "remove_sequence_item", schedule.remove_sequence_item, methods=("POST",))
app.add_url_rule("/schedule/sequences/<int:sequence_id>/replace", "replace_sequence_items", schedule.replace_sequence_items, methods=("POST",))

app.add_url_rule("/schedule/limits", "limits", schedule.limits, methods=("GET",))
app.add_url_rule("/schedule/limits/save", "save_limits", schedule.save_limits, methods=("POST",))

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

# Log

app.add_url_rule("/log", "log", log.log, methods=("GET",))
