import argparse
import cueparser
import re
import json
import sys
import os
import os.path
import shutil
from subprocess import check_call
from pprint import pprint

DEFAULT_PRINT_HEADER = '%performer% - %title%\n%file%\n%tracks%'
DEFAULT_PRINT_TRACK = '%performer% - %title%'

CUESHEET_FIELDS = [
        "performer",
        "songwriter",
        "title",
        "flags",
        "isrc"
    ]
TRACK_FIELDS = [
        "performer",
        "songwriter",
        "title",
        "index",
        "offset"
]
OFFSET_RE = re.compile(r'(\d+):(\d+)(:(\d+))?')

def offset2secs(offset):
    match = OFFSET_RE.match(offset)
    if not match:
        return None
    rv = float(int(match.group(1)) * 60 + int(match.group(2)))
    if match.group(4):
        rv += float(match.group(4)) * 0.001
    return rv


def track2dict(track, cuesheet):
    rv = {}
    for f in CUESHEET_FIELDS:
        v = getattr(cuesheet, f, None)
        if v:
            rv['c_%s' %f] = v
    for f in TRACK_FIELDS:
        v = getattr(track, f, None)
        if v:
            rv[f] = v

    return rv

def escape(s):
    return s.replace('"', '\"')

def tags2cue(infile, outfile, codec='utf-8'):
    with open(infile, "r", encoding=codec) as f:
        lines = f.readlines()
        #u8 = buffer.decode(codec or 'utf-8')
        #cuesheet.setData(buffer)
    lineno = 0

    out_performer = None

    # try to find the data file
    bn = os.path.basename(infile)
    def is_cadidate(c):
        if len(c) > 3 and c[-3:-1] == '.cue':
            return False
        if c[:len(bn)] == bn:
            return True
        return False
    candidates = list(filter(is_cadidate, os.path.dirname(infile)))
    if len(candidates) == 0:
        # default value
        data_file = "%s.wav" % os.path.splitext(bn)[0] 
    elif len(candidates) > 1:
        print("could not decide which source file to use. guessing %s" % data_file)
    else:
        data_file = candidates[0]

    out_tracks = []
    for line in lines:
        lineno += 1
        start, end, data = line.split("\t", 2)
        try:
            track_data = json.loads(data)
        except json.decoder.JSONDecodeError as e:
            print("Can't decode track data in line %s: %s" % (lineno, data))
            print(e)
            sys.exit(1)
        if not out_performer and 'c_performer' in track_data:
            out_performer = track_data['c_performer']
        out_tracks.append(
"""  TRACK {0} AUDIO
    TITLE "{1}"
    PERFORMER "{2}"
    INDEX {3} {4}""".format(lineno,
               escape(track_data.get("title", "UNKNOWN")),
               escape(track_data.get("performer", "UNKNOWN")),
               escape(track_data.get("index", "01")),
               escape(track_data.get("offset", "0:00:00")),
               ))

    if not out_performer:
        out_performer = 'Unknown'

    out = []
    out.append("PERFORMER \"%s\"" % out_performer)
    out.append("FILE \"%s\" WAVE" % data_file)
    if outfile:
        fp = open(outfile, "w")
    else:
        fp = sys.stdout
    for line in out + out_tracks:
        fp.write(line + "\n")

def cue2tags(infile, outfile, codec=None):
    cuesheet = cueparser.CueSheet()
    cuesheet.setOutputFormat(DEFAULT_PRINT_HEADER, DEFAULT_PRINT_TRACK)

    with open(infile, "r", encoding=codec) as f:
        buffer = f.read()
        #u8 = buffer.decode(codec or 'utf-8')
        cuesheet.setData(buffer)

    cuesheet.parse()
    # print(cuesheet.output())
    # print(cuesheet)
    for i, track in enumerate(cuesheet.tracks):
        data = track2dict(track, cuesheet)
        # calculate track length (roughly)
        start = offset2secs(track.offset)
        if i < len(cuesheet.tracks) - 1:
            end = offset2secs(cuesheet.tracks[i+1].offset)
        else:
            # print("Could not determin length of last song. Setting length to 1 minute")
            end = start + 60
        print('{}\t{}\t{}'.format(start, end, json.dumps(data)))

def escape_filename(fname):
    return fname.replace("/", "-")

def cmptracks(a, b):
    cm = 0
    for field in ["performer", "songwriter", "title"]:
        cm = cmp(getattr(a, field, None), getattr(b, field, None))
        print field, getattr(a, field, None), getattr(b, field, None), cm
        if cm != 0:
            return cm
    return cm


def formatcue(infile, format, unique=False, txt_header=None, txt_track=None):
    cuesheet = cueparser.CueSheet()
    cuesheet.setOutputFormat(txt_header or DEFAULT_PRINT_HEADER, txt_track or DEFAULT_PRINT_TRACK)

    with open(infile, "r") as f:
        buffer = f.read()
        #u8 = buffer.decode(codec or 'utf-8')
        cuesheet.setData(buffer)

    cuesheet.parse()
    if unique:
        new_tracks = []
        for track in cuesheet.tracks:
            # ineffient, who cares :)
            new = True
            for xtrack in new_tracks:
                if cmptracks(xtrack, track) == 0:
                    new = False
                    break
            if new:
                new_tracks.append(track)
        cuesheet.tracks = new_tracks

    print(cuesheet)


def splitcue(infile, format, codec=None):
    cuesheet = cueparser.CueSheet()
    cuesheet.setOutputFormat(DEFAULT_PRINT_HEADER, DEFAULT_PRINT_TRACK)

    with open(infile, "r") as f:
        buffer = f.read()
        #u8 = buffer.decode(codec or 'utf-8')
        cuesheet.setData(buffer)

    cuesheet.parse()
    print(cuesheet)
    print("splitting files")
    outdir = os.path.dirname(infile) or "."
    inname = os.path.basename(infile)

    check_call(["shntool", "split", 
                "-o", "flac",
                "-f", inname,
                cuesheet.file.replace('"', '')],
                cwd=outdir)
    # tag files

    # get global tags
    gtags = {}
    if cuesheet.rem:
        for line in cuesheet.rem.splitlines():
            chunks = str(line).split(" ", 2)
            if len(chunks) < 3:
                continue
            gtags[chunks[1]] = chunks[2].replace('"', '')
    gtags['ALBUM'] = cuesheet.title
    #import IPython
    #IPython.embed()
    move_targets = {}
    print("tagging split files")
    for i, track in enumerate(cuesheet.tracks):
        sn = os.path.join(outdir, "split-track%02d.flac" % track.number)
        args = ["metaflac", sn]
        tags = {}
        tags.update(gtags)
        if track.number:
            tags['TRACKNUMBER'] = track.number
        if track.title:
            tags['TITLE'] = track.title.replace('"', '')
        if track.performer:
            tags['ARTIST'] = track.performer.replace('"', '')
        if track.songwriter:
            tags['SONGWRITER'] = track.songwriter.replace('"', '')
        fname = os.path.join(outdir, escape_filename(format.format(**tags)))
        move_targets[sn] = fname
        for k,v in tags.items():
            args.append("--set-tag=%s=%s" %(k, v))
        print(args)
        check_call(args)
    print("moving files")
    for s, d in move_targets.items():
        print("%s -> %s" %(s, d))
        shutil.move(s, d)

def parse_args():
    parser = argparse.ArgumentParser(description='cueCommander cuesheet tools')
    subparsers = parser.add_subparsers(dest='todo')

    parser_auda = subparsers.add_parser('taglist', help='converts from/to audacity tagslits')
    auda_todo = parser_auda.add_mutually_exclusive_group(required=True)
    auda_todo.add_argument('--to-cue', action='store_true', dest='to_cue',
                    help='converts input file into cue file')
    auda_todo.add_argument('--to-tag', action='store_false', dest='to_cue',
                    help='converts input file into cue file')
    parser_auda.add_argument('--codec', dest='codec', default='utf-8',
                    help='codec of input file')

    parser_split = subparsers.add_parser('split', help='splits wav/flac files into tracks')
    parser_split.add_argument('input', help='input file')
    parser_split.add_argument('--format', help='format for output files',
                              default="{TRACKNUMBER:02d} - {TITLE}.flac")
    parser_split.add_argument('--codec', dest='codec', default='utf-8',
                    help='codec of input file')

    parser_split = subparsers.add_parser('format', help='formats cue files into different formats')
    parser_split.add_argument('input', help='input file')
    parser_split.add_argument('--format', help='output format',
                              default="text", choices=["text"])
    parser_split.add_argument('--txt-header', help='header format for text output',
                              default=DEFAULT_PRINT_HEADER)
    parser_split.add_argument('--txt-tracks', help='header format for text output',
                              default=DEFAULT_PRINT_TRACK)
    parser_split.add_argument('-u','--unique', dest="unique", help='remove duplicates',
                              action="store_true")


    args = parser.parse_args()

    if args.todo == 'taglist':
        if args.to_cue == False:
            cue2tags(args.input, args.output, codec=args.codec)
        else:
            tags2cue(args.input, args.output, codec=args.codec)
    elif args.todo == 'split':
        splitcue(args.input, args.format)
    elif args.todo == 'format':
        formatcue(args.input, args.format, unique=args.unique, txt_header=args.txt_header, txt_track=args.txt_tracks)
            


    # print(args)

# cuesheet = CueSheet()
# cuesheet.setOutputFormat(args.header, args.track)
# with open(cuefile, "r") as f:
#     cuesheet.setData(f.read())

# cuesheet.parse()
# print(cuesheet.output())

if __name__ == "__main__":
    parse_args()
