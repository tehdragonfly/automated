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


async def plan_attempt(target_length, error_margin, next_time, current_event, sequence, sequence_items):

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

        # Clear current event if we've reached the end.
        if current_event and current_event.end_time and current_event.end_time <= next_time:
            current_event = None

        # Check if we need a new sequence
        # or if the item list needs repopulating.
        # TODO get sequence from stream
        new_sequence = current_event.sequence if current_event and current_event.sequence else None
        if new_sequence != sequence or len(sequence_items) == 0:
            sequence = new_sequence
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
