from argparse import ArgumentParser

parser = ArgumentParser(description="Automation system.")
parser.add_argument("stream", help="Stream URL")

args = parser.parse_args()

