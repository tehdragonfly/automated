from collections import defaultdict
from datetime import time, timedelta
from flask import Flask, abort, redirect, render_template, request, url_for
from pydub import AudioSegment
from redis import StrictRedis
from sqlalchemy import and_
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import NoResultFound
from werkzeug import secure_filename

from automated.db import (
    Session,
    Category,
    ScheduleHour,
    Sequence,
    SequenceItem,
    Song,
    WeeklyEvent,
    string_to_timedelta,
)

redis = StrictRedis()

# Sequence schedule

def schedule():

    all_sequences = Session.query(Sequence).order_by(Sequence.name).all()

    schedule_hours = Session.query(ScheduleHour).options(joinedload(ScheduleHour.sequence))

    schedule = defaultdict(lambda: defaultdict(lambda: None))
    for sh in schedule_hours:
        schedule[sh.day][sh.hour] = sh.sequence

    schedule_table = defaultdict(lambda: [])
    for day in range(7):
        last_cw = None
        for hour in range(24):
            current_cw = schedule[day][hour]
            if hour!=0 and current_cw==last_cw:
                cell[1] += 1
                continue
            cell = [current_cw, 1]
            schedule_table[hour].append(cell)
            last_cw = current_cw

    return render_template(
        "schedule.html",
        section="schedule",
        page="schedule",
        all_sequences=all_sequences,
        current_sequence=None,
        schedule_table=schedule_table,
    )

def edit_schedule():

    try:
        day = int(request.form["day"])
        start_hour = int(request.form["start_hour"])
        end_hour = int(request.form["end_hour"])
    except (KeyError, ValueError):
        abort(400)

    schedule_range = range(start_hour, end_hour)
    if len(schedule_range)==0:
        return "", 204

    Session.query(ScheduleHour).filter(and_(
        ScheduleHour.day==day,
        ScheduleHour.hour>=start_hour,
        ScheduleHour.hour<end_hour,
    )).delete()

    try:
        sequence = Session.query(Sequence).filter(
            Sequence.id==int(request.form["sequence_id"])
        ).one()
    except (KeyError, ValueError, NoResultFound):
        return redirect(url_for("schedule"))

    for hour in schedule_range:
        Session.add(ScheduleHour(day=day, hour=hour, sequence_id=sequence.id))

    return redirect(url_for("schedule"))

# Sequences

def sequence(sequence_id):

    all_sequences = Session.query(Sequence).order_by(Sequence.name).all()

    try:
        sequence = Session.query(Sequence).filter(Sequence.id==sequence_id).one()
    except NoResultFound:
        abort(404)

    items = Session.query(SequenceItem).filter(
        SequenceItem.sequence_id==sequence.id
    ).order_by(SequenceItem.number).options(joinedload(SequenceItem.category)).all()

    all_categories = Session.query(Category).order_by(Category.name).all()

    return render_template(
        "sequence.html",
        section="schedule",
        all_sequences=all_sequences,
        current_sequence=sequence,
        items=items,
        all_categories=all_categories,
    )

def new_sequence():
    if "name" not in request.form or request.form["name"]=="":
        return "Please enter a name for the new sequence.", 400
    sequence = Sequence(name=request.form["name"])
    Session.add(sequence)
    Session.flush()
    return redirect(url_for("sequence", sequence_id=sequence.id))

def add_sequence_item(sequence_id):
    try:
        sequence = Session.query(Sequence).filter(Sequence.id==sequence_id).one()
        category = Session.query(Category).filter(Category.id==int(request.form["category_id"])).one()
    except (ValueError, NoResultFound):
        abort(404)
    items = Session.query(SequenceItem).filter(
        SequenceItem.sequence==sequence
    ).order_by(SequenceItem.number).all()
    Session.add(SequenceItem(
        sequence=sequence,
        number=items[-1].number+1 if len(items)!=0 else 1,
        category=category,
    ))
    return redirect(url_for("sequence", sequence_id=sequence.id))

def remove_sequence_item(sequence_id):
    Session.query(SequenceItem).filter(and_(
        SequenceItem.sequence_id==sequence_id,
        SequenceItem.number==int(request.form["number"]),
    )).delete()
    return redirect(url_for("sequence", sequence_id=sequence_id))

def replace_sequence_items(sequence_id):
    try:
        sequence = Session.query(Sequence).filter(Sequence.id==sequence_id).one()
    except NoResultFound:
        abort(404)
    try:
        ids = [int(_) for _ in request.form["categories"].split(",")]
    except ValueError:
        abort(400)
    try:
        categories = [
            Session.query(Category).filter(Category.id==category_id).one()
            for category_id in ids
        ]
    except NoResultFound:
        abort(404)
    Session.query(SequenceItem).filter(
        SequenceItem.sequence==sequence,
    ).delete()
    for number, category in enumerate(categories, 1):
        Session.add(SequenceItem(
            sequence=sequence,
            number=number,
            category=category,
        ))
    return "", 204

# Limits

def limits():
    all_sequences = Session.query(Sequence).order_by(Sequence.name).all()
    return render_template(
        "limits.html",
        section="schedule",
        page="limits",
        all_sequences=all_sequences,
        song_limit=timedelta(0, float(redis.get("song_limit") or 0)),
        artist_limit=timedelta(0, float(redis.get("artist_limit") or 0)),
    )

def save_limits():
    try:
        redis.set(
            "song_limit",
            string_to_timedelta(request.form["song_limit"]).total_seconds(),
        )
        redis.set(
            "artist_limit",
            string_to_timedelta(request.form["artist_limit"]).total_seconds(),
        )
    except ValueError:
        return "Please enter a time in the form hh:mm:ss.", 400
    return redirect(url_for("limits"))

# Events

def event_list():

    all_sequences = Session.query(Sequence).order_by(Sequence.name).all()

    events = Session.query(WeeklyEvent).order_by(WeeklyEvent.day, WeeklyEvent.time).all()

    day_names = {
        0: "Mon",
        1: "Tue",
        2: "Wed",
        3: "Thu",
        4: "Fri",
        5: "Sat",
        6: "Sun",
    }

    return render_template(
        "event_list.html",
        section="schedule",
        page="events",
        all_sequences=all_sequences,
        events=events,
        day_names=day_names,
    )

def new_event():

    try:
        day = int(request.form["day"])
        if day not in range(7):
            raise ValueError
    except ValueError:
        return "Invalid day.", 400

    try:
        time_parts = request.form["time"].split(":")
        if len(time_parts)!=3:
            raise ValueError
        event_time = time(*(int(_) for _ in time_parts))
    except ValueError:
        return "Please enter a time in the form HH:MM:SS.", 400

    error_margin = request.form["error_margin"].strip()
    if len(error_margin)==0:
        error_margin = timedelta(0)
    else:
        try:
            error_margin = string_to_timedelta(error_margin)
        except ValueError:
            return "Please enter an error margin in the form MM:SS.", 400

    if request.form["type"] not in WeeklyEvent.type.property.columns[0].type.enums:
        return "Invalid type.", 400

    name = request.form["name"].strip()[:50]
    if len(name)==0:
        return "Please enter a name.", 400

    # Audio events only
    if request.form["type"]=="audio":

        event_file = request.files["file"]
        try:
            segment = AudioSegment.from_file(event_file)
        except:
            return "That doesn't appear to be a valid audio file. Accepted formats are WAV, MP3 and OGG.", 400

        length = request.form["length"].strip()
        if len(length)==0:
            length = timedelta(0, segment.duration_seconds)
        else:
            try:
                length = string_to_timedelta(length)
            except ValueError:
                return "Please enter a length in the form MM:SS.", 400

    event = WeeklyEvent(
        day=day,
        time=event_time,
        error_margin=error_margin,
        name=name,
        type=request.form["type"],
    )
    Session.add(event)
    Session.flush()

    if request.form["type"]=="audio":
        event.length = length
        event.filename = ("%s_%s" % (event.id, secure_filename(event_file.filename)))[:100]
        event_file.seek(0)
        event_file.save("events/"+event.filename)

    return redirect(request.headers["Referer"])

def delete_event(event_id):
    Session.query(WeeklyEvent).filter(WeeklyEvent.id==event_id).delete()
    return redirect(request.headers["Referer"])

