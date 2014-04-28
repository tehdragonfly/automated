from collections import defaultdict
from flask import Flask, abort, redirect, render_template, request, url_for
from sqlalchemy import and_
from sqlalchemy.orm import joinedload
from sqlalchemy.orm.exc import NoResultFound

from db import Session, Category, Clockwheel, ClockwheelHour, ClockwheelItem, Song

def schedule():

    all_clockwheels = Session.query(Clockwheel).order_by(Clockwheel.name).all()

    clockwheel_hours = Session.query(ClockwheelHour).options(joinedload(ClockwheelHour.clockwheel))

    schedule = defaultdict(lambda: defaultdict(lambda: None))
    for ch in clockwheel_hours:
        schedule[ch.day][ch.hour] = ch.clockwheel

    # XXX COMMENT THE FUCK OUT OF THIS
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
        all_clockwheels=all_clockwheels,
        current_clockwheel=None,
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

    Session.query(ClockwheelHour).filter(and_(
        ClockwheelHour.day==day,
        ClockwheelHour.hour>=start_hour,
        ClockwheelHour.hour<end_hour,
    )).delete()

    try:
        clockwheel = Session.query(Clockwheel).filter(
            Clockwheel.id==int(request.form["clockwheel_id"])
        ).one()
    except (KeyError, ValueError, NoResultFound):
        return redirect(url_for("schedule"))

    for hour in schedule_range:
        Session.add(ClockwheelHour(day=day, hour=hour, clockwheel_id=clockwheel.id))

    return redirect(url_for("schedule"))

def clockwheel(clockwheel_id):

    all_clockwheels = Session.query(Clockwheel).order_by(Clockwheel.name).all()

    try:
        clockwheel = Session.query(Clockwheel).filter(Clockwheel.id==clockwheel_id).one()
    except NoResultFound:
        abort(404)

    items = Session.query(ClockwheelItem).filter(
        ClockwheelItem.clockwheel_id==clockwheel.id
    ).order_by(ClockwheelItem.number).options(joinedload(ClockwheelItem.category)).all()

    all_categories = Session.query(Category).order_by(Category.name).all()

    return render_template(
        "clockwheel.html",
        section="schedule",
        all_clockwheels=all_clockwheels,
        current_clockwheel=clockwheel,
        items=items,
        all_categories=all_categories,
    )

def new_clockwheel():
    if "name" not in request.form or request.form["name"]=="":
        abort(400)
    clockwheel = Clockwheel(name=request.form["name"])
    Session.add(clockwheel)
    Session.flush()
    return redirect(url_for("clockwheel", clockwheel_id=clockwheel.id))

def add_clockwheel_item(clockwheel_id):
    try:
        clockwheel = Session.query(Clockwheel).filter(Clockwheel.id==clockwheel_id).one()
        category = Session.query(Category).filter(Category.id==int(request.form["category_id"])).one()
    except (ValueError, NoResultFound):
        abort(404)
    items = Session.query(ClockwheelItem).filter(
        ClockwheelItem.clockwheel==clockwheel
    ).order_by(ClockwheelItem.number).all()
    Session.add(ClockwheelItem(
        clockwheel=clockwheel,
        number=items[-1].number+1 if len(items)!=0 else 1,
        category=category,
    ))
    return redirect(url_for("clockwheel", clockwheel_id=clockwheel.id))

def remove_clockwheel_item(clockwheel_id):
    Session.query(ClockwheelItem).filter(and_(
        ClockwheelItem.clockwheel_id==clockwheel_id,
        ClockwheelItem.number==int(request.form["number"]),
    )).delete()
    return redirect(url_for("clockwheel", clockwheel_id=clockwheel_id))


















