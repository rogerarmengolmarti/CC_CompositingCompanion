# ////////////////////////////////////////////////////////////////////
# CC_CompositingCompanion - backDropFunction.py
# ////////////////////////////////////////////////////////////////////

import os
import nuke

import colorsys
import random

def selectedNodes():
    """Returns a list of currently selected nodes in the Nuke script."""
    return nuke.selectedNodes()

def _calculate_z_order(nodes, padding=100):

    if not nodes:
        return 0

    Z_STEP = 1

    nx1 = min(n.xpos() for n in nodes) - padding
    ny1 = min(n.ypos() for n in nodes) - padding
    nx2 = max(n.xpos() + n.screenWidth() for n in nodes) + padding
    ny2 = max(n.ypos() + n.screenHeight() for n in nodes) + padding

    def bounds(bd):
        x1 = bd.xpos()
        y1 = bd.ypos()
        return x1, y1, x1 + bd['bdwidth'].value(), y1 + bd['bdheight'].value()

    def overlaps(bx1, by1, bx2, by2):
        return nx1 < bx2 and nx2 > bx1 and ny1 < by2 and ny2 > by1

    def contains(bx1, by1, bx2, by2):
        """True if the new backdrop fully contains this existing one."""
        return nx1 <= bx1 and ny1 <= by1 and nx2 >= bx2 and ny2 >= by2

    def contained_by(bx1, by1, bx2, by2):
        """True if the new backdrop is fully inside this existing one."""
        return bx1 <= nx1 and by1 <= ny1 and bx2 >= nx2 and by2 >= ny2

    floor_z    = None
    ceiling_z  = None

    for bd in nuke.allNodes('BackdropNode'):
        bx1, by1, bx2, by2 = bounds(bd)
        if not overlaps(bx1, by1, bx2, by2):
            continue
        z = int(bd['z_order'].value())
        if contained_by(bx1, by1, bx2, by2):
            floor_z = max(floor_z, z) if floor_z is not None else z
        elif contains(bx1, by1, bx2, by2):
            ceiling_z = min(ceiling_z, z) if ceiling_z is not None else z

    if floor_z is None and ceiling_z is None:
        return 0
    if floor_z is None:
        return ceiling_z - Z_STEP
    if ceiling_z is None:
        return floor_z + Z_STEP


    mid = (floor_z + ceiling_z) // 2
    return mid if mid > floor_z else floor_z + 1

def createBackDrop(data):

    
    nodes = selectedNodes()

    #Values
    padding = 100
    font_size = data.get('size', 25)
    default_z_order = _calculate_z_order(nodes, padding)
    if data.get('center', True) == True:
        title = data.get('name', "")
        backDrop_title = f"<center>{title}"
    else:
        backDrop_title = data.get('name', "")
    bold = data.get('bold', False)
    itailcs = data.get('italics', False)

    # Color
    color = data.get('color',"#3a3a3a")
    color = color.lstrip('#')
    r, g, b = int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16)
    backDrop_color = (r << 24) | (g << 16) | (b << 8) | 0xFF

    # Bounds
    x_min = min(node.xpos() for node in nodes)
    y_min = min(node.ypos() for node in nodes)
    x_max = max(node.xpos() + node.screenWidth() for node in nodes)
    y_max = max(node.ypos() + node.screenHeight() for node in nodes)
    
    # Create backdrop
    bd = nuke.createNode('BackdropNode')

    bd.setXpos(x_min - padding)
    bd.setYpos(y_min - padding)

    bd.knob('bdwidth').setValue(x_max - x_min + 2 * padding)
    bd.knob('bdheight').setValue(y_max - y_min + 2 * padding)

    bd.knob('label').setValue(backDrop_title)
    font = bd.knob('note_font').value()
    if bold:
        font += " Bold"
    if itailcs:
        font += " Italic"
    bd.knob('note_font').setValue(font)
    bd.knob('note_font_size').setValue(font_size)
    bd.knob('z_order').setValue(default_z_order)

    bd.knob('tile_color').setValue(backDrop_color)

    bd.knob('appearance').setValue('Fill' if data.get('filled', True) else 'Border')
    bd.knob('bookmark').setValue(data.get('bookmark', False))
    