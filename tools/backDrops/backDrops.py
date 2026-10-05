# ////////////////////////////////////////////////////////////////////
# CC_CompositingCompanion - backDrops.py
# ////////////////////////////////////////////////////////////////////

import os
import sys
import importlib
import nuke

keyShortCut = 'Ctrl+B'

_UTILS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'utils_bkdrp')


def run():
    nodes = nuke.selectedNodes()
    if not nodes:
        nuke.message("Please select at least one node to create a backdrop.")
        return

    print('[CC] Backdrop creator starting')

    if _UTILS_DIR not in sys.path:
        sys.path.insert(0, _UTILS_DIR)

    import backDropFunctions
    import backDropUI

    # Reload so edits are picked up without restarting Nuke (remove for release)
    importlib.reload(backDropFunctions)
    importlib.reload(backDropUI)

    backDropUI.show_floating()