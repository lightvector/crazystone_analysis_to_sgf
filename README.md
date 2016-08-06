# crazystone_analysis_to_sgf
Convert a [CrazyStone](http://www.remi-coulom.fr/CrazyStone/) XPS / OXPS analysis file to SGF

To use:

* In CrazyStone, use the Print option to produce an XPS or OXPS file of the analysis
* Open that file with the script (i.e. send the script an argument to the filepath)
* If all goes well, the SGF will appear
* Run with -help to display optional parameters.

Features:

* CrazyStone's favourite move is shown as a circle (minor preference), triangle (moderate preference), or square (strong preference).
* Various information is displayed in the comments.
* Moves that CrazyStone thought were particularly bad are flagged with a hotspot property. Some SGF editors such as [Sabaki](https://github.com/yishn/Sabaki) allow you to easily find these (press F2 in Sabaki)
* Applies some transformations to CrazyStone's reported win ratio in a way that should correspond a bit better with "real" winning chances, at least for strong kyu to dan level players. (To also see untransformed values, use the flag -include-raw).
* The delta reported between CrazyStone's favorite move and the game move is similarly transformed, giving hopefully a better measure of the actual goodness/badness of a move. and along with a threshold greatly reduces the frequency with which CrazyStone flags moves in winning/losing positions that wouldn't have actually made a difference or weren't even actually mistakes.

Limitations:

* Can't determine board size from the input; use --board-size 9 or whatever in the arguments (anywhere in the argument list)
* The location of handicap stones has to be guessed: free handicaps will be placed wrong, and handicap 3 is dubious.
