# ////////////////////////////////////////////////////////////////////
# CC_CompositingCompanion - writeBackdrop.py
# ////////////////////////////////////////////////////////////////////




import json
import os
import nuke

from variables import CCVariables
ccVars = CCVariables()

# ----- Directory paths -----
ICONS_DIR  = ccVars.ICONS_DIR
TOOLS_DIR = ccVars.TOOLS_DIR

PRESETS_PATH = os.path.join(TOOLS_DIR, 'backDrops', 'utils_bkdrp', 'backdrop_presets.json')


def _load() -> dict:
    if not os.path.exists(PRESETS_PATH):
        return {"presets": []}
    with open(PRESETS_PATH, "r") as f:
        return json.load(f)


def _save(data: dict):
    with open(PRESETS_PATH, "w") as f:
        json.dump(data, f, indent=4)


def list_presets():
    data = _load()
    for p in data["presets"]:
        print(f"  {p['name']:20s}  color={p['color']}  bold={p['bold']}  "
              f"italics={p['italics']}  size={p['size']}")
    return data["presets"]


def add_preset(name: str,
               color: str = "#3a3a3a",
               bold: bool = True,
               italics: bool = False,
               center: bool = True,
               bookmark: bool = True,
               size: int = 25):
    """Add or overwrite a preset entry."""
    data = _load()
    # Overwrite if name already exists
    data["presets"] = [p for p in data["presets"] if p["name"] != name]
    data["presets"].append({
        "name":     name,
        "color":    color,
        "bold":     bold,
        "italics":  italics,
        "center":   center,
        "bookmark": bookmark,
        "size":     size,
    })
    _save(data)

def save_preset_from_selected():
    """Read settings from the selected BackdropNode and save as a preset."""
    selected = nuke.selectedNodes('BackdropNode')
    
    if not selected:
        nuke.message("No BackdropNode selected.")
        return
    if len(selected) > 1:
        nuke.message("Please select only one BackdropNode.")
        return

    bd = selected[0]

    # Strip <center> tag from label if present
    label = bd['label'].value()
    name  = label.replace('<center>', '').strip() or bd.name()

    # Unpack tile_color int back to hex
    packed = int(bd['tile_color'].value())
    r = (packed >> 24) & 0xFF
    g = (packed >> 16) & 0xFF
    b = (packed >>  8) & 0xFF
    color = '#{:02x}{:02x}{:02x}'.format(r, g, b)

    # Read font for bold/italic
    font  = bd['note_font'].value()
    bold    = 'Bold'   in font
    italics = 'Italic' in font

    data = {
        'name':     name,
        'color':    color,
        'bold':     bold,
        'italics':  italics,
        'center':   '<center>' in label,
        'bookmark': bool(bd['bookmark'].value()),
        'size':     int(bd['note_font_size'].value()),
    }

    add_preset(**data)
    nuke.message(f"[CC] Saved preset '{name}' from node {bd.name()}")


def remove_preset(name: str):
    """Remove a preset by name."""
    data = _load()
    before = len(data["presets"])
    data["presets"] = [p for p in data["presets"] if p["name"] != name]
    if len(data["presets"]) < before:
        _save(data)
        print(f"[preset_writer] Removed preset '{name}'")
    else:
        print(f"[preset_writer] Preset '{name}' not found")


def run():
    try:
        save_preset_from_selected()
    except:
        print("[CC] - Backdrop preset save failed.")
        nuke.message("Error saving preset.")


#keyShortCut = 'Ctrl+Shift+Alt+B' disabeled shortcut
