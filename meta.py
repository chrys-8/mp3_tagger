from argparse import ArgumentParser
from dataclasses import dataclass
from mutagen.easyid3 import EasyID3
from pathlib import Path

import random

TrackType = str|None
MatchType = tuple[int,int]

@dataclass
class AlbumMetadata:
    artist: str
    album: str
    tracklist: list[str]

@dataclass
class FileChanges:
    path: Path
    track: TrackType = None
    match: tuple[int,int] = (0,0)

class AlbumMetadataError(Exception):
    pass

class UserQuit(Exception):
    pass

class UserSkip(Exception):
    pass

def removeBOM(line: str) -> str:
    ''' Remove BOM at beginning of file'''
    lineBytes = [ord(c) for c in line[:5]]
    if lineBytes[0] == 0xfeff:
        return line[1:]
    return line

def readMetadataFile(path: Path) -> dict[str,list[str]]:
    '''Read metadata into table entries'''
    data = {'': []}
    currentHeader = ''

    def processLine(line: str) -> tuple[str,str|None]:
        entry = line.rstrip()
        header = entry[1:-1] if entry.startswith('[') and entry.endswith(']') else None
        return entry,header

    with open(path, 'r', encoding = "utf-8") as file:
        for idx,line in enumerate(file.readlines()):
            line = removeBOM(line) if idx == 0 else line
            entry,header = processLine(line)
            if len(entry) == 0:
                continue

            if header is not None and header in data.keys():
                currentHeader = header
                continue

            if header is not None:
                currentHeader = header
                data[header] = []
                continue

            else:
                data[currentHeader].append(entry)

    return data

ARTIST_HEADER = 'artist'
ALBUM_HEADER = 'album'
TRACKLIST_HEADER = 'tracklist'

def parseAlbumDataTable(data: dict[str,list[str]]) -> AlbumMetadata:
    '''Construct AlbumMetadata from data table'''
    headerExists = lambda header: len(data.get(header, list())) > 0
    if not headerExists(ARTIST_HEADER):
        raise AlbumMetadataError(f"No {ARTIST_HEADER}")
    if not headerExists(ALBUM_HEADER):
        raise AlbumMetadataError(f"No {ALBUM_HEADER}")
    if not headerExists(TRACKLIST_HEADER):
        raise AlbumMetadataError(f"No {TRACKLIST_HEADER}")

    return AlbumMetadata(
            data[ARTIST_HEADER][0],
            data[ALBUM_HEADER][0],
            data[TRACKLIST_HEADER])

def isSkippableChar(ch: str) -> bool:
    '''Is character considered skippable'''
    return ch.isspace() or ch in '()[]{}'

def lowercaseSkippedString(string: str) -> str:
    '''Convert string to lowercase and skipped skippabled characters'''
    unskippable = lambda ch: not isSkippableChar(ch)
    return ''.join(filter(unskippable, string.lower()))

def makeSkippedStringMap(string: str) -> list[int]:
    '''Make a map for converting skipped string indices to original string indices'''
    return [idx for idx,ch in enumerate(string) if not isSkippableChar(ch)]

def matchStrings(string: str, pattern: str) -> MatchType:
    '''Yield longest match between string and pattern'''
    assert len(string) > 0
    assert len(pattern) > 0

    if len(pattern) > len(string):
        return 0,0

    # using pattern as sliding window
    for offset in range(len(string) - len(pattern) + 1):
        windowedString = string[offset:offset + len(pattern)]
        if windowedString == pattern:
            return offset,len(pattern)

    return 0,0

def identifyTrackFromFilePath(path: Path, tracklist: list[str]) -> tuple[TrackType,int,int]:
    '''Identify which track in the tracklist corresponds with the file'''
    bestMatch: TrackType = None
    bestMatchStart = 0
    bestMatchLength = 0
    file = lowercaseSkippedString(path.stem)
    for trackTitle in tracklist:
        track = lowercaseSkippedString(trackTitle)
        matchStart,matchLength = matchStrings(file, track)
        if matchLength > bestMatchLength:
            bestMatch = trackTitle
            bestMatchStart = matchStart
            bestMatchLength = matchLength

    return bestMatch,bestMatchStart,bestMatchLength

def splitMatchedString(string: str, matchStart: int, matchLength: int) -> tuple[str,str,str]:
    '''Split string into pre-,matched,post-matched for match against skipped string'''
    indexMap = makeSkippedStringMap(string)
    start = indexMap[matchStart]
    end = indexMap[matchStart + matchLength - 1] + 1
    return string[:start],string[start:end],string[end:]

ESCAPE = "\x1b"
FG_DEFAULT = ESCAPE + "[39m"
FG_GREEN = ESCAPE + "[32m"
FG_RED = ESCAPE + "[31m"
FG_YELLOW = ESCAPE + "[33m"
FG_BLUE = ESCAPE + "[34m"
FG_MAGENTA = ESCAPE + "[35m"
FG_CYAN = ESCAPE + "[36m"

def printFileChange(changes: FileChanges):
    '''Prints out changes to a file'''
    if changes.track is None:
        START = FG_YELLOW
        END = FG_DEFAULT
        print(f"{START}'{changes.path.name}' will remain unchanged{END}")
#        print(f"{path.name} will remain unchanged")
    elif changes.match != (0,0):
        START = FG_CYAN
        END = FG_DEFAULT
        matchStart,matchLength = changes.match
        pre,match,post = splitMatchedString(changes.path.name, matchStart, matchLength)
        print(f"{pre}{START}{match}{END}{post} -> {START}{changes.track}{END}")
#        print(f"{path.name} -> {track}")
    else:
        START = FG_CYAN
        END = FG_DEFAULT
        print(f"{START}{changes.path.name}{END} -> {START}{changes.track}{END}")
#        print(f"{path.name} -> {track}")

def printFileChangesSummary(fileChanges: list[FileChanges]):
    '''Prints out summary of changes to be made'''
    for idx,change in enumerate(fileChanges):
        print(f"{idx + 1} - ", end = '')
        printFileChange(change)

QUIT = 'q'
SKIP = 's'
QUIT_SKIP = 'qs'

def promptBoundedInteger(prompt: str, bounds: tuple[int,int], signal = QUIT) -> int:
    '''Prompt user for bounded integer input or quit'''
    lower,upper = bounds
    choice: int|None = None
    while choice is None:
        print(prompt, end = '')
        response = input()
        if response == '' and SKIP in signal:
            raise UserSkip

        if response.lower() == 'q' and QUIT in signal:
            raise UserQuit

        try:
            choice = int(response)
            if choice < lower or choice > upper:
                print("Selection is outside the available range")
                choice = None

        except ValueError:
            continue

    return choice

PROMPT_TRACK_SELECT = "Select the track number ('q' quits): "
PROMPT_TRACK_SELECT_EXTRA = "Enter number of any selection you want to change: (empty skips, 'q' quits) "

def promptTrackSelect(tracklist: list[str]) -> TrackType:
    '''Prompt user to select track from tracklist'''
    print("0 - <remove track title>")
    for idx,track in enumerate(tracklist):
        print(f"{idx + 1} - {track}")

    print()
    choice = promptBoundedInteger(PROMPT_TRACK_SELECT, bounds = (0,len(tracklist)))
    if choice == 0:
        return None
    else:
        return tracklist[choice - 1]

def promptChanges(fileChanges: list[FileChanges], tracklist: list[str]) -> list[FileChanges]:
    '''Prompt user for additional changes'''
    while True:
        try:
            print()
            printFileChangesSummary(fileChanges)
            print()
            choice = promptBoundedInteger(PROMPT_TRACK_SELECT_EXTRA, bounds=(1,len(fileChanges)), signal = QUIT_SKIP)

            changes = fileChanges[choice - 1]
            printFileChange(changes)

            newTrack = promptTrackSelect(tracklist)
            changes.track = newTrack
            changes.match = (0,0)
            printFileChange(changes)

        except UserSkip:
            return fileChanges

def saveChanges(fileChanges: list[FileChanges], album: AlbumMetadata):
    '''Save file changes to the filesystem'''
    for changes in fileChanges:
        path = changes.path
        track = changes.track
        if track is not None:
            audio = EasyID3(path)
            audio["artist"] = album.artist
            audio["albumartist"] = album.artist
            audio["album"] = album.album
            track = changes.track
            audio["title"] = track
            audio["tracknumber"] = str(album.tracklist.index(track) + 1)
            audio.save()

def thankyou() -> str:
    '''Say thank you'''
    THANKS = ["See you next time!",
              "Hellothankyouforwatching! Hellothankyouforwatching!",
              "Good-bye!",
              "Thanks for using my script!",
              "Until next time!",
              "See you soon!",
              ]

    return random.choice(THANKS)

# Program Arguments
argParser = ArgumentParser(prog = "Album Metadatiser", description = "Put the metadata!")
argParser.add_argument("input", type = Path)

def main():
    args = argParser.parse_args()
    albumDataPath: Path = args.input

    album: AlbumMetadata
    try:
        data = readMetadataFile(albumDataPath)
        album = parseAlbumDataTable(data)
        print(f"Read album metadata from {albumDataPath}")

    except AlbumMetadataError as err:
        print(f"Error: {err!s}")
        print("Fix error and run script again")
        return

    audioPaths = Path(".").glob("*.mp3")

    fileChanges: list[FileChanges] = []
    for path in audioPaths:
        trackTitle,matchStart,matchLength = identifyTrackFromFilePath(path, album.tracklist)
        fileChanges.append(FileChanges(path,trackTitle,(matchStart,matchLength)))

    try:
        promptChanges(fileChanges, album.tracklist)

    except UserQuit:
        print("Quitting...")
        print("No changes were made to the files.")
        return

    saveChanges(fileChanges, album)
    print("Changes saved to files!")
    print(thankyou())

if __name__ == "__main__":
    main()

