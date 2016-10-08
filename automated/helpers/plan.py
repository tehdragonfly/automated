import asyncio

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from automated.helpers.schedule import (
    pick_song,
    populate_sequence_items,
)

TEN_MINUTES = timedelta(0, 600)

loop = asyncio.get_event_loop()
executor = ThreadPoolExecutor()


class PastTargetTime(Exception): pass


async def generate_plan(next_time, target_object, sequence, sequence_items, use_sequence_until=None):

    print("TARGET:", target_object)

    if target_object.start_time <= next_time:
        raise PastTargetTime

    print("TARGET TIME:", target_object.start_time)
    target_length = target_object.start_time - next_time
    print("TARGET LENGTH:", target_length)

    # Start by making 10 attempts...
    attempts, errors = await asyncio.wait([
        plan_attempt(next_time, target_length, target_object.error_margin, sequence, sequence_items, use_sequence_until)
        for n in range(10)
    ])
    candidates = [_.result() for _ in attempts]
    # TODO do something with errors

    # ...and if that didn't give us any good plans, try another 100.
    if not any(attempt["can_shorten"] or attempt["can_lengthen"] for attempt in candidates):
        attempts, errors = await asyncio.wait([
            plan_attempt(next_time, target_length, target_object.error_margin, sequence, sequence_items, use_sequence_until)
            for n in range(10)
        ])
        candidates += [_.result() for _ in attempts]
        # TODO do something with errors

    # Hopefully we should be able to find a successful plan in 10
    # attempts. For the particularly hard ones we can try 100, but
    # after that it's pretty unlikely that we can meet the target
    # time, so we just give up at that point.

    candidates.sort(key=lambda a: (
        0 if a["can_shorten"] or a["can_lengthen"] else 1,
        min(a["distance"], a["mls_distance"]),
    ))

    plan = candidates[0]

    for song in plan["songs"]:
        print(song)

    if plan["can_shorten"] and plan["can_lengthen"]:

        # Do whichever is closer.
        print("CAN SHORTEN OR LENGTHEN.")
        print("SHORTEN DISTANCE:", plan["distance"])
        print("LENGTHEN DISTANCE:", plan["mls_distance"])

        if plan["distance"] < plan["mls_distance"]:
            print("SHORTENING")
            songs = shorten(
                plan["songs"],
                plan["distance"],
                target_object.error_margin,
            )
        else:
            print("LENGTHENING")
            songs = lengthen(
                plan["songs"][:-1],
                plan["mls_distance"],
                target_object.error_margin,
            )

    elif plan["can_shorten"]:

        # Shorten.
        print("CAN SHORTEN ONLY.")
        print("SHORTEN DISTANCE:", plan["distance"])
        songs = shorten(
            plan["songs"],
            plan["distance"],
            target_object.error_margin,
        )

    elif plan["can_lengthen"]:

        # Lengthen.
        print("CAN LENGTHEN ONLY.")
        print("LENGTHEN DISTANCE:", plan["mls_distance"])
        songs = lengthen(
            plan["songs"][:-1],
            plan["mls_distance"],
            target_object.error_margin,
        )

    else:

        # Do whichever is closer.
        print("NEITHER.")

        print("SHORTEN DISTANCE:", plan["distance"])
        print("LENGTHEN DISTANCE:", plan["mls_distance"])

        if plan["distance"] < plan["mls_distance"]:
            print("SHORTENING")
            songs = plan["songs"]
            for song in songs:
                song[1] = song[0].min_length
        else:
            print("LENGTHENING")
            songs = plan["songs"][:-1]
            for song in songs:
                song[1] = song[0].max_length

    return songs, plan["sequence"], plan["sequence_items"]


async def plan_attempt(next_time, target_length, error_margin, sequence, sequence_items, use_sequence_until=None):

    min_target_length = target_length - error_margin
    max_target_length = target_length + error_margin

    attempt_length = timedelta(0)
    attempt_min_length = timedelta(0)
    attempt_max_length = timedelta(0)

    # Clone this so we don't alter the original.
    sequence_items = list(sequence_items)

    songs = []

    continues = 0

    while attempt_length < target_length:

        # Cancel if we run out of songs.
        if continues == 10:
            break

        remaining_time = target_length - attempt_length

        attempt_songs = set(_[0].id for _ in songs)
        attempt_artists = set()
        for song, length in songs:
            for artist in song.artists:
                attempt_artists.add(artist.id)

        if sequence is None or len(sequence_items) == 0:

            # If there isn't a sequence, just pick any song.
            song = await loop.run_in_executor(
                executor, pick_song,
                next_time, None,
                attempt_songs, attempt_artists,
                remaining_time if remaining_time <= TEN_MINUTES else None,
            )

        else:

            # Otherwise pick songs from the sequence.
            item, category = sequence_items.pop(0)
            song = await loop.run_in_executor(
                executor, pick_song,
                next_time, category.id,
                attempt_songs, attempt_artists,
                remaining_time if remaining_time <= TEN_MINUTES else None,
            )

        if song is None:
            continues += 1
            continue

        continues = 0

        songs.append([song, song.length])

        attempt_length += song.length
        attempt_min_length += song.min_length
        attempt_max_length += song.max_length

        next_time += song.length

        # Reset the sequence if necessary.
        if use_sequence_until and next_time > use_sequence_until:
            print("EVENT OVER, RESETTING SEQUENCE")
            # TODO get default sequence from stream
            sequence = None
            sequence_items = await loop.run_in_executor(executor, populate_sequence_items, sequence)

        # Or just check if the item list needs repopulating.
        elif len(sequence_items) == 0:
            print("REPOPULATING SEQUENCE_ITEMS")
            sequence_items = await loop.run_in_executor(executor, populate_sequence_items, sequence)

    can_shorten = attempt_min_length <= max_target_length
    can_lengthen = attempt_max_length - songs[-1][0].max_length >= min_target_length

    return {
        "songs": songs,
        "sequence": sequence,
        "sequence_items": sequence_items,
        # Full lengths
        "length": attempt_length,
        "min_length": attempt_min_length,
        "max_length": attempt_max_length,
        "distance": attempt_length-target_length,
        # Lengths minus last song
        "mls_length": attempt_length-songs[-1][0].length,
        "mls_min_length": attempt_min_length-songs[-1][0].min_length,
        "mls_max_length": attempt_max_length-songs[-1][0].max_length,
        "mls_distance": target_length-(attempt_length-songs[-1][0].length),
        # Validity
        "can_shorten": can_shorten,
        "can_lengthen": can_lengthen,
    }


def shorten(songs, distance, error_margin):
    while distance > error_margin:
        for song in songs:
            # Shorten each item by whichever is smallest:
            # - distance remaining
            # - song shortenability
            # - one second
            shorten_by = min(
                distance,
                song[1] - song[0].min_length,
                timedelta(0, 1),
            )
            song[1] -= shorten_by
            distance -= shorten_by
    return songs


def lengthen(songs, distance, error_margin):
    while distance > error_margin:
        for song in songs:
            # Lengthen each item by whichever is smallest:
            # - distance remaining
            # - song lengthenability
            # - one second
            lengthen_by = min(
                distance,
                song[0].max_length - song[1],
                timedelta(0, 1),
            )
            song[1] += lengthen_by
            distance -= lengthen_by
    return songs
