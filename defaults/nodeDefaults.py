import nuke



# Shuffle2
nuke.knobDefault("Shuffle2.label", "[value in1]")

# Crop
nuke.knobDefault("Crop.crop", "false")

# STMap
nuke.knobDefault("STMap.uv", "rgb")

# Viewer
nuke.knobDefault("Viewer.hide_input", "true")

# Merge2
nuke.knobDefault("Merge2.bbox", "B")

# LayerContactSheet
nuke.knobDefault("LayerContactSheet.showLayerNames", "true")

# Inpaint2
nuke.knobDefault("Inpaint2.fillRegion", "Matte Alpha")





# Shuffle
nuke.knobDefault("Shuffle.label", "[value in]")
