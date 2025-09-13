from argparse import ArgumentParser
from dataclasses import dataclass
from mutagen.easyid3 import EasyID3
from pathlib import Path

import random

@dataclass
class AlbumMetadata:
    artist: str
    album: str
    tracklist: list[str]

class AlbumMetadataError(Exception):
    pass

class UserQuit(Exception):
    pass

class UserSkip(Exception):
    pass

FileChangesType = list[tuple[Path,str|None]]

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

def matchStrings(string: str, pattern: str) -> int:
    '''Yield longest match between string and pattern'''
    assert len(string) > 0
    assert len(pattern) > 0

    # heuristics
    if len(pattern) > len(string):
        return 0

    # using pattern as sliding window
    for offset in range(len(string) - len(pattern) + 1):
        windowedString = string[offset:offset + len(pattern)]
        if windowedString == pattern:
            return len(pattern)

    return 0

def identifyTrackFromFilePath(path: Path, tracklist: list[str]) -> str|None:
    '''Identify which track in the tracklist corresponds with the file'''
    bestMatch: str|None = None
    bestMatchLength = 0
    file = lowercaseSkippedString(path.stem)
    for trackTitle in tracklist:
        track = lowercaseSkippedString(trackTitle)
        matchLength = matchStrings(file, track)
        if matchLength > bestMatchLength:
            bestMatch = trackTitle
            bestMatchLength = matchLength

    return bestMatch

ESCAPE = "\x1b"
FG_DEFAULT = ESCAPE + "[39m"
FG_GREEN = ESCAPE + "[32m"
FG_RED = ESCAPE + "[31m"
FG_YELLOW = ESCAPE + "[33m"
FG_BLUE = ESCAPE + "[34m"
FG_MAGENTA = ESCAPE + "[35m"
FG_CYAN = ESCAPE + "[36m"

def printFileChange(path: Path, track: str|None):
    '''Prints out changes to a file'''
    if track is None:
        print(f"{FG_YELLOW}{path.stem} will remain unchanged{FG_DEFAULT}")
#        print(f"{path.stem} will remain unchanged")
    else:
        print(f"{FG_CYAN}{path.stem}{FG_DEFAULT} -> {FG_CYAN}{track}{FG_DEFAULT}")
#        print(f"{path.stem} -> {track}")

def printFileChangesSummary(fileChanges: FileChangesType):
    '''Prints out summary of changes to be made'''
    for idx,change in enumerate(fileChanges):
        path,track = change
        print(f"{idx + 1} - ", end = '')
        printFileChange(path, track)

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

def promptTrackSelect(tracklist: list[str]) -> str:
    '''Prompt user to select track from tracklist'''
    for idx,track in enumerate(tracklist):
        print(f"{idx + 1} - {track}")

    print()
    choice = promptBoundedInteger(PROMPT_TRACK_SELECT, bounds = (1,len(tracklist)))
    return choice - 1

def promptChanges(fileChanges: FileChangesType, tracklist: list[str]) -> FileChangesType:
    '''Prompt user for additional changes'''
    while True:
        try:
            print()
            printFileChangesSummary(fileChanges)
            print()
            choice = promptBoundedInteger(PROMPT_TRACK_SELECT_EXTRA, bounds=(1,len(fileChanges)), signal = QUIT_SKIP)

            path,track = fileChanges[choice - 1]
            printFileChange(path, track)
            newTrack = tracklist[promptTrackSelect(tracklist)]
            printFileChange(path, newTrack)
            fileChanges[choice - 1] = (path,newTrack)

        except UserSkip:
            return fileChanges

def saveChanges(fileChanges: FileChangesType, album: AlbumMetadata):
    '''Save file changes to the filesystem'''
    for path,track in fileChanges:
        audio = EasyID3(path)
        audio["artist"] = album.artist
        audio["albumartist"] = album.artist
        audio["album"] = album.album
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
              "See you soon!"
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

    fileChanges: FileChangesType = []
    for path in audioPaths:
        trackTitle: str|None = identifyTrackFromFilePath(path, album.tracklist)
        fileChanges.append((path,trackTitle))

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

