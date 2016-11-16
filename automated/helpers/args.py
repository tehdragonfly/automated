from argparse import ArgumentParser

parser = ArgumentParser(description="Automation system.")
parser.add_argument("stream", help="Stream URL")

parser.add_argument("--song-path", help="Song path")
parser.add_argument("--audio-path", help="Audio event path")

args = parser.parse_args()

