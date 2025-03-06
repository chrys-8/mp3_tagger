from argparse import ArgumentParser
from mutagen.easyid3 import EasyID3
from pathlib import Path

# Program Arguments
argParser = ArgumentParser(prog = "Album Metadatiser", description = "Put the metadata!")
argParser.add_argument("input", type = Path)
args = argParser.parse_args()
albumDataPath: Path = args.input


# Album Parameters
artist: str = ""
album: str = ""
tracklist: list[str] = []
with open(albumDataPath, 'r') as albumData:
    parseState = 0
    for line in albumData.readlines():
        line = line.rstrip()
        if parseState == 0:
            if "[artist]" in line:
                parseState = 1
                continue

            if "[album]" in line:
                parseState = 2
                continue

            if "[tracklist]" in line:
                parseState = 3
                continue

            continue

        if parseState == 1:
            if not line:
                continue

            artist = line
            parseState = 0
            continue

        if parseState == 2:
            if not line:
                continue

            album = line
            parseState = 0
            continue

        if parseState == 3:
            if not line:
                continue

            tracklist.append(line.lower())
            continue

if not artist:
    raise ValueError("No artist")
if not album:
    raise ValueError("No album")
if not tracklist:
    raise ValueError("No tracklist")

audioPaths = Path(".").glob("*.mp3")
for audioPath in audioPaths:
    audio = EasyID3(audioPath)
    audio["artist"] = artist
    audio["albumartist"] = artist
    audio["album"] = album

    title = audioPath.stem
    audio["title"] = title

    try:
        trackn = tracklist.index(title.lower()) + 1

    except ValueError:
        print(f"Unknown track: {title}")
        continue

    audio["tracknumber"] = str(trackn)
    audio.save()
