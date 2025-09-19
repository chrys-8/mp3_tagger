from argparse import ArgumentParser
from dataclasses import dataclass, field
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

MAX_NUMBER_OF_MISSES = 2

@dataclass
class Match:
    start: int
    length: int
    misses: tuple[int,...] = tuple()

    def __eq__(self, other):
        return self.start == other.start and self.length == other.length

USER_DEF_MATCH = Match(-1, -1)
NO_MATCH = Match(0, 0)

@dataclass
class PathTitleMatch:
    path: Path
    match: Match
    title: str = ""

    def __bool__(self):
        '''Object is True if title is given, else False'''
        return len(self.title) != 0

class AlbumMetadataError(Exception):
    pass

class UserQuit(Exception):
    pass

class UserCancel(Exception):
    pass

class UserDone(Exception):
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

SKIPPABLE_CHARS = '()[]{}-_'

def isSkippableChar(ch: str) -> bool:
    '''Is character considered skippable'''
    return ch.isspace() or ch in SKIPPABLE_CHARS

def lowercaseSkippedString(string: str) -> str:
    '''Convert string to lowercase and skipped skippabled characters'''
    unskippable = lambda ch: not isSkippableChar(ch)
    return ''.join(filter(unskippable, string.lower()))

def makeSkippedStringMap(string: str) -> list[int]:
    '''Make a map for converting skipped string indices to original string indices'''
    return [idx for idx,ch in enumerate(string) if not isSkippableChar(ch)]

def findMismatchedCharIndices(a: str, b: str) -> list[int]:
    '''Find list of indices of mismatched characters in two equal-length strings'''
    assert len(a) == len(b)
    return [index for index,ch in enumerate(a) if ch != b[index]]

def matchStrings(string: str, pattern: str) -> Match:
    '''Yield longest match between string and pattern'''
    assert len(string) > 0
    assert len(pattern) > 0

    if len(pattern) > len(string):
        return NO_MATCH

    # using pattern as sliding window
    for offset in range(len(string) - len(pattern) + 1):
        windowedString = string[offset:offset + len(pattern)]
        mismatchedCharIdxs = findMismatchedCharIndices(windowedString, pattern)
        if len(mismatchedCharIdxs) <= MAX_NUMBER_OF_MISSES:
            correctedIdxs = tuple(idx + offset for idx in mismatchedCharIdxs)
            return Match(offset,len(pattern),correctedIdxs)

    return NO_MATCH

def identifyTrackFromFilePath(path: Path, tracklist: list[str]) -> tuple[str|None,Match]:
    '''Identify which track in the tracklist corresponds with the file'''
    bestTitleGuess: str|None = None
    bestMatch = NO_MATCH
    file = lowercaseSkippedString(path.stem)
    for title in tracklist:
        skippedTitle = lowercaseSkippedString(title)
        match = matchStrings(file, skippedTitle)
        if match == NO_MATCH:
            continue

        if match.length > bestMatch.length and len(match.misses) <= len(bestMatch.misses):
            bestTitleGuess = title
            bestMatch = match
            continue

        if len(match.misses) < len(bestMatch.misses):
            bestTitleGuess = title
            bestMatch = match
            continue

        if bestMatch == NO_MATCH:
            bestTitleGuess = title
            bestMatch = match
            continue

    return bestTitleGuess,bestMatch

def formatPartiallyMatchedString(string: str, match: Match, START: str, SKIP: str, END: str) -> str:
    '''Format partially matched string with highlight codes'''
    indexMap = makeSkippedStringMap(string)
    start = indexMap[match.start]
    end = indexMap[match.start + match.length - 1] + 1
    skips = [indexMap[idx] for idx in match.misses]

    # add format tokens in reverse order to preserve indices
    tokens = list(string)
    tokens.insert(end, END)
    for skip in reversed(skips):
        tokens.insert(skip + 1, START)
        tokens.insert(skip, SKIP)

    tokens.insert(start, START)
    return ''.join(tokens)

ESCAPE = "\x1b"
FG_DEFAULT = ESCAPE + "[39m"
FG_GREEN = ESCAPE + "[32m"
FG_RED = ESCAPE + "[31m"
FG_YELLOW = ESCAPE + "[33m"
FG_BLUE = ESCAPE + "[34m"
FG_MAGENTA = ESCAPE + "[35m"
FG_CYAN = ESCAPE + "[36m"

def displayPathTitleMatch(pathMatch: PathTitleMatch) -> None:
    '''Display path and matching title'''
    if pathMatch.match == USER_DEF_MATCH:
        START = FG_CYAN
        END = FG_DEFAULT
        print(f"{START}{pathMatch.path.name} -> {pathMatch.title}{END}")
        return

    if pathMatch:
        START = FG_CYAN
        SKIP = FG_RED
        END = FG_DEFAULT
        filename = formatPartiallyMatchedString(
                pathMatch.path.name, pathMatch.match, START = START, SKIP = SKIP, END = END)
        print(f"{filename} -> {START}{pathMatch.title}{END}")
        return

    START = FG_YELLOW
    END = FG_DEFAULT
    print(f"{START}'{pathMatch.path.name}' will remain unchanged{END}")
    return

def displayMatchSummary(pathTitleMatches: list[PathTitleMatch]) -> None:
    '''Display summary of which paths were matched to which titles'''
    for idx,change in enumerate(pathTitleMatches):
        print(f"{idx + 1} - ", end = '')
        displayPathTitleMatch(change)

# signals
QUIT = 'q'
CANCEL = 's'
DONE = 'd'

QUIT_CANCEL = QUIT + CANCEL
QUIT_DONE = QUIT + DONE

QUIT_PROMPT_HINT = "'q' quits"
CANCEL_PROMPT_HINT = "return cancels"
DONE_PROMPT_HINT = "return finishes"

def addSignalHintsToPrompt(prompt: str, signal: str) -> str:
    '''Format prompt with signal hints'''
    hints = []
    if CANCEL in signal:
        hints.append(CANCEL_PROMPT_HINT)
    if DONE in signal:
        hints.append(DONE_PROMPT_HINT)
    if QUIT in signal:
        hints.append(QUIT_PROMPT_HINT)

    if len(hints) == 0:
        return prompt.format(hints = "")
    else:
        return prompt + f" ({', '.join(hints)}) "

def addPromptPadding(prompt: str) -> str:
    '''Add padding to the end of a prompt string'''
    return prompt + ' ' if prompt[-1] != ' ' else prompt

def promptBoundedInteger(prompt: str, bounds: tuple[int,int], signal: str) -> int:
    '''Prompt user for bounded integer input or quit'''
    lower,upper = bounds
    choice: int|None = None
    prompt = addSignalHintsToPrompt(prompt, signal)
    prompt = addPromptPadding(prompt)
    while choice is None:
        print(prompt, end = '')
        response = input()
        if response == '' and CANCEL in signal:
            raise UserCancel

        if response == '' and DONE in signal:
            raise UserDone

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

PROMPT_SELECT_NEW_TRACK = "Select the new track number:"
PROMPT_SELECT_TRACK_CHANGE = "Enter number of any selection you want to change:"

def promptTrackSelect(tracklist: list[str]) -> TrackType:
    '''Prompt user to select track from tracklist'''
    print("0 - <remove track title>")
    for idx,track in enumerate(tracklist):
        print(f"{idx + 1} - {track}")

    print()
    choice = promptBoundedInteger(PROMPT_SELECT_NEW_TRACK, bounds = (0,len(tracklist)), signal = QUIT_CANCEL)
    if choice == 0:
        return None
    else:
        return tracklist[choice - 1]

def promptChanges(pathTitleMatches: list[PathTitleMatch], tracklist: list[str]) -> list[PathTitleMatch]:
    '''Prompt user for additional changes'''
    while True:
        try:
            print()
            displayMatchSummary(pathTitleMatches)
            print()
            choice = promptBoundedInteger(PROMPT_SELECT_TRACK_CHANGE, bounds=(1,len(pathTitleMatches)), signal = QUIT_DONE)

            ptm = pathTitleMatches[choice - 1]
            displayPathTitleMatch(ptm)

            newTitle = promptTrackSelect(tracklist)
            ptm.title = newTitle if newTitle is not None else ''
            ptm.match = USER_DEF_MATCH
            displayPathTitleMatch(ptm)

        except UserCancel:
            print("Cancelled new track selection")
            continue

        except UserDone:
            return pathTitleMatches

def maybeTrackMetadata(pathMatch: PathTitleMatch, album: AlbumMetadata) -> dict[str,str]|None:
    '''Determine metadata for a track, if any'''
    if not pathMatch:
        return None

    return {
            "artist" : album.artist,
            "albumartist" : album.artist,
            "album" : album.album,
            "title" : pathMatch.title,
            "tracknumber" : str(album.tracklist.index(pathMatch.title) + 1),
            }

def writeMetadata(path: Path, metadata: dict[str,str]) -> None:
    '''Write metadata from dict to file'''
    artist = metadata.get("artist")
    albumartist = metadata.get("albumartist")
    album = metadata.get("album")
    title = metadata.get("title")
    tracknumber = metadata.get("tracknumber")

    audio = EasyID3(path)
    if artist is not None:
        audio["artist"] = artist
    if albumartist is not None:
        audio["albumartist"] = albumartist
    if album is not None:
        audio["album"] = album
    if title is not None:
        audio["title"] = title
    if tracknumber is not None:
        audio["tracknumber"] = tracknumber
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
    # NOTICE REMOVE WHEN FIXED
    print("Notice: title highlighting may not work as intended")
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

    pathTitleMatches: list[PathTitleMatch] = []
    for path in audioPaths:
        title,match = identifyTrackFromFilePath(path, album.tracklist)
        pathTitleMatches.append(
                PathTitleMatch(path, match, title)
                if title is not None
                else PathTitleMatch(path, NO_MATCH))

    try:
        promptChanges(pathTitleMatches, album.tracklist)

    except UserQuit:
        print("Quitting...")
        print("No changes were made to the files.")
        return

    fnTrackMeta = lambda ptm: maybeTrackMetadata(ptm, album)
    tracksMetadata = [metadata
                      for metadata in map(fnTrackMeta, pathTitleMatches)
                      if metadata is not None]

    if len(tracksMetadata) == 0:
        print("No changes were made to the files")
        print(thankyou())
        return

    for metadata in tracksMetadata:
        writeMetadata(metadata)

    print("Changes saved to files!")
    print(thankyou())

if __name__ == "__main__":
    main()

