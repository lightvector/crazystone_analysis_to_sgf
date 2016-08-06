#!/usr/bin/python3
# -*- coding: utf-8 -*-

# CrazyStone Analysis to SGF
# Original: https://github.com/fohristiwhirl/crazystone_analysis_to_sgf
# Modified by lightvector to add useful flags and transformations of the evals and deltas
#
# The problem: CrazyStone Deep Learning 1.0 (released 2016-05-16) can analyse a game but the only output
# is via printing its "Record Analysis List" from the Print menu. Fortunately, you can usually "print" it
# to an XPS or OXPS file.
#
# Such files are actually just zip-compressed directories that contain some other files. So conversion to
# an SGF is just a matter of reading the right files in the archive and using the info contained therein.

# Run with --help for usage.

import codecs, re, sys, zipfile, argparse, traceback, math

HOTSPOT_DELTA = 0.10  # Hotspot (sgf: "HO[1]") if delta >= this, and display square
TRIANGLE_DELTA = 0.06  # Triangle if delta >= this

DEFAULT_STDEV = 0.15  # Stdev of bell curve whose cdf we take to be the "real" probability given CS's probability

# We tighten the stdev on the bell curve cdf yet further for CS's move suggestions, to further increase its prospensity
# to only suggest moves that might make a difference to the game result under good play.
STDEV_FOR_REPORT_FACTOR = 0.7

# We report CS's suggested moves only if it thinks they are sufficiently much better than our moves.
# But we loosen the threshold for moves that are near recent moves, to allow CS more leeway in suggesting
# local improvements to moves, or suggesting that we shouldn't have tenukied when we do so without hammering
# in that we should still go back there on every subsequent move (unless it's really big)

# Max distance in map
REPORT_DELTA_DISTANCE_MAX = 16

# When CS move is this far from <something>, report it if the delta is greater than this.
REPORT_DELTA_BY_DISTANCE = {
  0: 0.008,
  1: 0.008,
  2: 0.008,
  3: 0.009,
  4: 0.010,
  5: 0.012,
  6: 0.014,
  7: 0.016,
  8: 0.018,
  9: 0.020,
  10: 0.022,
  11: 0.024,
  12: 0.026,
  13: 0.028,
  14: 0.028,
  15: 0.028,
  16: 0.028,
}

# Scaling factors for <something> for REPORT_DELTA_BY_DISTANCE
FROM_OWN_MOVE = 2.0
FROM_OPP_MOVE = 2.0
FROM_OWN_PREV_MOVE = 3.0


class BadFile(Exception): pass

UNICODE_STRING_REGEX = r'UnicodeString="(.+)"'

def point_from_english_string(s, boardsize): # "C17" ---> "(3,3)"
  if len(s) not in [2,3]:
    raise ValueError
  s = s.upper()
  xlookup = " ABCDEFGHJKLMNOPQRSTUVWXYZ"
  x = xlookup.index(s[0])               # Could raise ValueError
  y = boardsize - int(s[1:]) + 1            # Could raise ValueError
  return (x,y)

def sgf_point_from_english_string(s, boardsize): # "C17" ---> "cc"
  (x,y) = point_from_english_string(s,boardsize)
  return sgf_point_from_point(x, y)


def sgf_point_from_point(x, y):             # 3,3 --> "cc"
  if x < 1 or x > 26 or y < 1 or y > 26:
    raise ValueError
  s = ""
  s += chr(x + 96)
  s += chr(y + 96)
  return s

def euclidean_distance(p0,p1):
  (x0,y0) = p0
  (x1,y1) = p1
  return int(round(math.sqrt((x1-x0)*(x1-x0) + (y1-y0) * (y1-y0))))

def handicap_points(boardsize, handicap, tygem = False):

  points = set()

  if boardsize < 4:
    return points

  if handicap > 9:
    handicap = 9

  if boardsize < 7:
    d = 1
  elif boardsize < 13:
    d = 2
  else:
    d = 3

  if handicap >= 2:
    points.add((boardsize - d, 1 + d))
    points.add((1 + d, boardsize - d))

  # Experiments suggest Tygem puts its 3rd handicap stone in the top left

  if handicap >= 3:
    if tygem:
      points.add((1 + d, 1 + d))
    else:
      points.add((boardsize - d, boardsize - d))

  if handicap >= 4:
    if tygem:
      points.add((boardsize - d, boardsize - d))
    else:
      points.add((1 + d, 1 + d))

  if boardsize % 2 == 0:    # No handicap > 4 on even sided boards
    return points

  mid = (boardsize + 1) // 2

  if handicap in [5, 7, 9]:
    points.add((mid, mid))

  if handicap >= 6:
    points.add((1 + d, mid))
    points.add((boardsize - d, mid))

  if handicap >= 8:
    points.add((mid, 1 + d))
    points.add((mid, boardsize - d))

  return points


def get_metadata(strings):
  metadata = dict()

  for s in strings:
    if s.startswith("Black: "):
      metadata["PB"] = s[7:].replace("…", "...")
    if s.startswith("White: "):
      metadata["PW"] = s[7:].replace("…", "...")
    if s.startswith("Komi: "):
      try:
        metadata["KM"] = float(s[6:])
      except:
        pass
    if s.startswith("Handicap Stones: "):
      try:
        metadata["HA"] = int(s[17:])
      except:
        pass
    if s.startswith("Status: "):
      if "Time up. Black loses" in s:
        metadata["RE"] = "W+T"
      if "Time up. White loses" in s:
        metadata["RE"] = "B+T"
      if "Black has resigned" in s:
        metadata["RE"] = "W+R"
      if "White has resigned" in s:
        metadata["RE"] = "B+R"
      if "White wins by" in s:
        try:
          metadata["RE"] = "W+" + re.search(r'White wins by (.+) points', s).group(1)
        except:
          pass
      if "Black wins by" in s:
        try:
          metadata["RE"] = "B+" + re.search(r'Black wins by (.+) points', s).group(1)
        except:
          pass

    if len(s) == 10 and s[4] == "/" and s[7] == "/":
      try:
        year = int(s[0:4])
        month = int(s[5:7])
        day = int(s[8:10])
        metadata["DT"] = "{:04d}-{:02d}-{:02d}".format(year, month, day)
      except:
        pass

  metadata["GM"] = 1
  metadata["FF"] = 4
  metadata["CA"] = "UTF-8"
  return metadata

# Example move string: "17 K,1600:00:00102260.5070411.5±16 F,170.001037"
# Meaning:
#
# Move 17, K16 was played, thinking time was 00:00:00, 10226 playouts,
# Black wins P = 0.507041, projected score = 1.5±16, CrazyStone prefers
# F17, delta is 0.001037
def extract_move_data(s):
  actual_move = None
  crazy_move = None
  delta = None
  winrate = None

  MOVE_REGEX = r'([A-Z],[ \d]\d)'
  OTHER_MOVE_REGEX = r'([A-Z],[ \d]\d)(.*)$' # needs to be run on only the latter part of the string, else it will get 1st move
  SITUATION_REGEX = r'(0\.\d\d\d\d)'

  # First REGEX
  extract = re.search(MOVE_REGEX, s)
  # If there actually is a move
  if extract:
    actual_move = extract.group(1)
    letter = actual_move[0]
    number = int(actual_move[2:])
    actual_move = (letter,number)

    # Second REGEX
    extract = re.search(OTHER_MOVE_REGEX, s[8:])  # Don't start at start so as not to get the first move
    if extract:
      crazy_move = extract.group(1)
      letter = crazy_move[0]
      number = int(crazy_move[2:])
      crazy_move = (letter,number)

      if extract.group(2) != "---":
        delta = float(extract.group(2))

    # Third REGEX
    extract = re.search(SITUATION_REGEX, s)
    if extract:
      winrate = float(extract.group(1))

  return (actual_move,crazy_move,delta,winrate)

# Make a function that applies a transform to the winrate that stretches out the middle range and squashes the extreme ranges,
# to make it a more linear measure of advantage and better suppress crazystone's bad suggestions in won/lost games.
# Currently, the CDF of the probability distribution from 0 to 1 given by x^k * (1-x)^k, where k is set to be the value such that
# the stdev of the distribution is stdev.

def winrate_transformer(stdev):
  def logfactorial(x):
    return math.lgamma(x+1)
  # Variance of the distribution =
  # = The integral from 0 to 1 of (x-0.5)^2 x^k (1-x)^k dx
  # = (via integration by parts)  (k+2)!k! / (2k+3)! - (k+1)!k! / (2k+2)! + (1/4) * k!^2 / (2k+1)!
  #
  # Normalize probability by dividing by the integral from 0 to 1 of x^k (1-x)^k dx :
  # k!^2 / (2k+1)!
  # And we get:
  # (k+1)(k+2) / (2k+2) / (2k+3) - (k+1) / (2k+2) + (1/4)
  def variance(k):
    k = float(k)
    return (k+1) * (k+2) / (2*k+2) / (2*k+3) - (k+1) / (2*k+2) + 0.25
  # Perform binary search to find the appropriate k
  def find_k(lower,upper):
    while True:
      mid = 0.5 * (lower + upper)
      if mid == lower or mid == upper or lower >= upper:
        return mid
      var = variance(mid)
      if var < stdev * stdev:
        upper = mid
      else:
        lower = mid

  if stdev * stdev <= 1e-10:
    raise ValueError("Stdev too small, please choose a more reasonable value")

  # Repeated doubling to find an upper bound big enough
  upper = 1
  while variance(upper) > stdev * stdev:
    upper = upper * 2

  k = find_k(0,upper)
  print("Using k={}, stdev={}".format(k,math.sqrt(variance(k))))

  def unnormpdf(x):
    if x <= 0 or x >= 1 or 1-x <= 0:
      return 0
    a = math.log(x)
    b = math.log(1-x)
    logprob = a * k + b * k
    # Constant scaling so we don't overflow floats with crazy values
    logprob = logprob - 2 * k * math.log(0.5)
    return math.exp(logprob)

  #Precompute a big array to approximate the CDF
  n = 100000
  lookup = [ unnormpdf(float(x)/float(n)) for x in range(n+1) ]
  cum = 0
  for i in range(n+1):
    cum += lookup[i]
    lookup[i] = cum
  for i in range(n+1):
    lookup[i] = lookup[i] / lookup[n]

  def cdf(x):
    i = math.floor(x * n)
    if i == n:
      return lookup[i]
    excess = x * n - i
    return lookup[i] + excess * (lookup[i+1] - lookup[i])

  return (lambda x: cdf(x))


def make_sgf_file_from_archive(arch, boardsize, outfilename, tygem, transform_winrate, transform_winrate_for_should_display_cs, include_raw, sensitivity_factor):
  pages = []

  n = 1
  while True:
    try:
      decompressed_page = arch.open("Documents/1/Pages/{}.fpage".format(n))
      pages.append(decompressed_page)
    except:
      break
    n += 1

  if len(pages) == 0:
    raise BadFile

  lines = []

  for page in pages:
    for line in codecs.iterdecode(page, encoding = "utf8", errors = "replace"):
      lines.append(line)

  strings = []

  for line in lines:
    extract = re.search(UNICODE_STRING_REGEX, str(line))
    if extract:
      strings.append(extract.group(1))

  metadata = get_metadata(strings)
  metadata["SZ"] = boardsize

  movestrings = []

  nextstart = 1
  for s in strings:
    startstring = "{} ".format(nextstart)
    if s.startswith(startstring):
      movestrings.append(s)
      nextstart += 1

  sgf = "(;"
  colour = "B"
  last_point = (boardsize/2,boardsize/2)
  last_last_point = (boardsize/2,boardsize/2)

  def should_display_cs(delta,point,crazy_point):
    distance = euclidean_distance(crazy_point,point)
    last_distance = euclidean_distance(crazy_point,last_point)
    last_last_distance = euclidean_distance(crazy_point,last_last_point)
    if distance > REPORT_DELTA_DISTANCE_MAX:
      distance = REPORT_DELTA_DISTANCE_MAX
    if last_distance > REPORT_DELTA_DISTANCE_MAX:
      last_distance = REPORT_DELTA_DISTANCE_MAX
    if last_last_distance > REPORT_DELTA_DISTANCE_MAX:
      last_last_distance = REPORT_DELTA_DISTANCE_MAX
    delta_needed = REPORT_DELTA_BY_DISTANCE[distance] / sensitivity_factor * FROM_OWN_MOVE
    last_delta_needed = REPORT_DELTA_BY_DISTANCE[last_distance] / sensitivity_factor * FROM_OPP_MOVE
    last_last_delta_needed = REPORT_DELTA_BY_DISTANCE[last_last_distance] / sensitivity_factor * FROM_OWN_PREV_MOVE
    return delta >= delta_needed or delta >= last_delta_needed or delta >= last_last_delta_needed

  for key in metadata:
    sgf += key + "[" + str(metadata[key]) + "]"

  if metadata.get("HA"):
    colour = "W"
    points = handicap_points(boardsize, metadata["HA"], tygem)
    sgf += "AB"
    for point in points:
      sgf += "[{}]".format(sgf_point_from_point(point[0], point[1]))
    sgf += "C[WARNING: Handicap placement has been guessed at by crazy.py]"

  for s in movestrings:
    (actual_move,crazy_move,raw_delta,raw_winrate) = extract_move_data(s)

    if actual_move != None:
      (letter,number) = actual_move
      point = point_from_english_string("{}{}".format(letter, number), boardsize)
      sgf_move = sgf_point_from_english_string("{}{}".format(letter, number), boardsize)
      sgf += ";{}[{}]".format(colour, sgf_move)
      comment = ""
      raw_comment = ""

      if raw_winrate != None:
        winrate = transform_winrate(raw_winrate)
        comment += "Black Adjusted Winrate: {:.1f} %\n\n".format(winrate * 100)
        raw_comment += "Black Raw Winrate: {:.1f} %\n".format(raw_winrate * 100)
      else:
        comment += "\n"
        raw_comment += "\n"

      if crazy_move != None and crazy_move != actual_move and raw_delta != None and raw_winrate != None:

        if colour == "B":
          delta = transform_winrate(raw_winrate + raw_delta) - transform_winrate(raw_winrate)
          delta_for_should_display = transform_winrate_for_should_display_cs(raw_winrate + raw_delta) - transform_winrate_for_should_display_cs(raw_winrate)
        else:
          delta = transform_winrate(raw_winrate) - transform_winrate(raw_winrate - raw_delta)
          delta_for_should_display = transform_winrate_for_should_display_cs(raw_winrate) - transform_winrate_for_should_display_cs(raw_winrate - raw_delta)

        (letter,number) = crazy_move
        crazy_point = point_from_english_string("{}{}".format(letter, number), boardsize)
        sgf_move = sgf_point_from_english_string("{}{}".format(letter, number), boardsize)

        if should_display_cs(delta_for_should_display,point,crazy_point):
          if delta_for_should_display >= HOTSPOT_DELTA:
            sgf += "SQ[{}]".format(sgf_move)
            sgf += "HO[1]"
            comment += "CS **STRONGLY** prefers {}{}!!\n".format(letter, number)
          elif delta_for_should_display >= TRIANGLE_DELTA:
            sgf += "TR[{}]".format(sgf_move)
            comment += "CS prefers {}{}.\n".format(letter, number)
          else:
            sgf += "CR[{}]".format(sgf_move)
            comment += "CS slightly prefers {}{}.\n".format(letter, number)
          comment += "Adjusted Delta: {:.1f} %\n".format(delta * 100)
          raw_comment += "Raw Delta: {:.1f} %\n".format(raw_delta * 100)
        else:
          comment += "\n\n"
          raw_comment += "\n"
      else:
        comment += "\n\n"
        raw_comment += "\n"

      if include_raw:
        comment += "\n\n\n"
        comment += raw_comment

      # Done
      comment = comment.strip()
      if comment:
        sgf += "C[{}]".format(comment)

      # Update for next move
      colour = "B" if colour == "W" else "W"
      last_last_point = last_point
      last_point = point

  sgf += ")"

  with open(outfilename, "w", encoding="utf8") as outfile:
    outfile.write(sgf)


def main():

  input_filepaths = []

  parser = argparse.ArgumentParser()
  parser.add_argument("-tygem", "--tygem", help="Tygem", action='store_true')
  parser.add_argument("-board-size", "--board-size", help="Board Size", default=19, type=int)
  parser.add_argument("-stdev", "--stdev", help="Stdev of bell curve to use for mapping from CS winrate to real prob of win", default=DEFAULT_STDEV, type=float)
  parser.add_argument("-include-raw", "--include-raw", help="Show raw CS win rates and deltas", action='store_true')
  parser.add_argument("-sensitivity-factor", "--sensitivity-factor", help="Higher = more marginal deltas. Lower = only the biggest deltas", default=1.0, type=float)
  parser.add_argument("files",nargs="*")
  args = parser.parse_args()

  transform_winrate = winrate_transformer(args.stdev)

  #Use a stricter transform for checking whether crazystone should display it, to try to reduce Crazystone's weird endgame suggestions
  #particularly when they don't actually affect the game result.
  transform_winrate_for_should_display_cs = winrate_transformer(args.stdev * STDEV_FOR_REPORT_FACTOR)

  for zfile in args.files:
    try:
      with zipfile.ZipFile(zfile) as arch:
        try:
          outfilename = "{}_analysis.sgf".format(zfile)
          make_sgf_file_from_archive(arch, args.board_size, outfilename, args.tygem, transform_winrate,
                                     transform_winrate_for_should_display_cs, args.include_raw, args.sensitivity_factor)
          print("{} converted to {}".format(zfile, outfilename))
        except:
          print("Couldn't parse {} at size {}".format(zfile, args.board_size))
          traceback.print_exc(file=sys.stderr)
    except:
      print("Couldn't open {} or interpret it as a zip file".format(zfile))
      traceback.print_exc(file=sys.stderr)

if __name__ == "__main__":
  main()
