"""Echo Deck: editable Blender concept, NOT dimensionally verified fabrication CAD.

Run with Blender 5: blender --background --python build_concept.py
Coordinates are illustrative millimetres. UI texture is a synthetic repo screenshot.
"""
import math
from pathlib import Path
import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'preview'
OUT.mkdir(parents=True, exist_ok=True)
UI = ROOT / 'reference' / 'display-home.png'
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
for item in list(bpy.data.materials):
    bpy.data.materials.remove(item)

scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'
scene.unit_settings.scale_length = 0.001
scene.render.engine = 'BLENDER_EEVEE'
scene.cycles.samples = 40
scene.cycles.use_denoising = True
scene.render.resolution_x = 1800
scene.render.resolution_y = 1400
scene.render.resolution_percentage = 100
scene.render.image_settings.file_format = 'PNG'
scene.render.film_transparent = False
scene.world.color = (0.3, 0.3, 0.3)
scene.view_settings.view_transform = 'AgX'
try:
    prefs = bpy.context.preferences.addons['cycles'].preferences
    prefs.compute_device_type = 'CUDA'
    prefs.get_devices()
    devices = [d for d in prefs.devices if d.type == 'CUDA']
    if devices:
        for d in prefs.devices:
            d.use = d.type == 'CUDA'
        scene.cycles.device = 'GPU'
        print('Rendering on CUDA', flush=True)
except Exception:
    pass

def mat(name, color, roughness=.45, metallic=0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes.get('Principled BSDF')
    p.inputs['Base Color'].default_value = (*color, 1)
    p.inputs['Roughness'].default_value = roughness
    p.inputs['Metallic'].default_value = metallic
    return m

navy = mat('Midnight | satin printed polymer', (.018, .037, .052), .32)
navy_light = mat('Rear cover | blue charcoal', (.038, .065, .078), .43)
black = mat('Soft black | seals and isolators', (.006, .009, .012), .66)
glass = mat('Black glass margin', (.006, .012, .017), .13)
silver = mat('Brushed aluminium', (.39, .44, .46), .32, .75)
mint = mat('Echo | mint inlay', (.10, .69, .62), .32, .3)
pcb = mat('Pi reference | PCB', (.018, .17, .086), .53)
copper = mat('Brass spacers', (.48, .25, .07), .32, .75)
darkpcb = mat('Audio reference | PCB', (.018, .04, .06), .5)
ribbon = mat('CSI ribbon', (.72, .73, .68), .58)
fabric = mat('Acoustic fabric | charcoal weave', (.075, .093, .10), .9)
n = fabric.node_tree.nodes
l = fabric.node_tree.links
tex = n.new('ShaderNodeTexNoise')
tex.inputs['Scale'].default_value = 280
tex.inputs['Detail'].default_value = 2
bump = n.new('ShaderNodeBump')
bump.inputs['Strength'].default_value = .38
bump.inputs['Distance'].default_value = .18
l.new(tex.outputs['Fac'], bump.inputs['Height'])
l.new(bump.outputs['Normal'], n.get('Principled BSDF').inputs['Normal'])
wood = mat('Warm wood | prototype frame reference', (.30, .135, .048), .42)
n = wood.node_tree.nodes
l = wood.node_tree.links
tc = n.new('ShaderNodeTexCoord')
mapping = n.new('ShaderNodeVectorMath')
mapping.operation = 'MULTIPLY'
mapping.inputs[1].default_value = (2.5, 25, 65)
noise = n.new('ShaderNodeTexNoise')
noise.inputs['Scale'].default_value = 3
noise.inputs['Detail'].default_value = 3
noise.inputs['Roughness'].default_value = .7
ramp = n.new('ShaderNodeValToRGB')
ramp.color_ramp.elements[0].position = .23
ramp.color_ramp.elements[0].color = (.125, .044, .017, 1)
ramp.color_ramp.elements[1].position = .77
ramp.color_ramp.elements[1].color = (.48, .26, .115, 1)
l.new(tc.outputs['Generated'], mapping.inputs[0])
l.new(mapping.outputs[0], noise.inputs['Vector'])
l.new(noise.outputs['Fac'], ramp.inputs[0])
l.new(ramp.outputs[0], n.get('Principled BSDF').inputs['Base Color'])
bump = n.new('ShaderNodeBump')
bump.inputs['Strength'].default_value = .15
bump.inputs['Distance'].default_value = .09
l.new(noise.outputs['Fac'], bump.inputs['Height'])
l.new(bump.outputs[0], n.get('Principled BSDF').inputs['Normal'])

def applymat(o, m):
    o.data.materials.append(m)
    return o

def bevel(o, radius=1, segments=4):
    if radius:
        mod = o.modifiers.new('Soft machined edges', 'BEVEL')
        mod.width = radius
        mod.segments = segments
    for p in o.data.polygons:
        p.use_smooth = True
    mod = o.modifiers.new('Weighted corner normals', 'WEIGHTED_NORMAL')
    mod.keep_sharp = True
    return o

def box(name, dims, loc, material, radius=1, parent=None):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc)
    o = bpy.context.object
    o.name = name
    o.dimensions = dims
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    applymat(o, material)
    bevel(o, radius)
    if parent:
        o.parent = parent
    return o

def cyl(name, radius, depth, loc, material, axis='Z', parent=None, vertices=96):
    bpy.ops.mesh.primitive_cylinder_add(vertices=vertices, radius=radius, depth=depth, location=loc)
    o = bpy.context.object
    o.name = name
    if axis == 'Y':
        o.rotation_euler[0] = math.pi / 2
    elif axis == 'X':
        o.rotation_euler[1] = math.pi / 2
    applymat(o, material)
    bevel(o, .3, 3)
    if parent:
        o.parent = parent
    return o

def curve(name, pts, width, material, parent=None):
    c = bpy.data.curves.new(name, 'CURVE')
    c.dimensions = '3D'
    c.resolution_u = 18
    c.bevel_depth = width
    c.bevel_resolution = 3
    sp = c.splines.new('BEZIER')
    sp.bezier_points.add(len(pts)-1)
    for point, co in zip(sp.bezier_points, pts):
        point.co = co
        point.handle_left_type = 'AUTO'
        point.handle_right_type = 'AUTO'
    o = bpy.data.objects.new(name, c)
    scene.collection.objects.link(o)
    applymat(o, material)
    if parent:
        o.parent = parent
    return o

def outline(w, h, r, steps=12):
    pts = []
    for cx, cz, start in [(w/2-r, h/2-r, 0), (-w/2+r, h/2-r, 90),
                           (-w/2+r, -h/2+r, 180), (w/2-r, -h/2+r, 270)]:
        for k in range(steps+1):
            a = math.radians(start + 90*k/steps)
            pts.append((cx+r*math.cos(a), cz+r*math.sin(a)))
    return pts

def frame(name, outer, inner, depth, y, material, parent):
    op, ip = outline(*outer), outline(*inner)
    N = len(op)
    verts = [(x, yy, z) for yy in [y-depth/2, y+depth/2] for points in [op, ip] for x,z in points]
    faces = []
    for i in range(N):
        j = (i+1) % N
        faces.extend([(i,j,N+j,N+i), (2*N+j,2*N+i,3*N+i,3*N+j),
                      (j,i,2*N+i,2*N+j), (N+i,N+j,3*N+j,3*N+i)])
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    o = bpy.data.objects.new(name, mesh)
    scene.collection.objects.link(o)
    applymat(o, material)
    bevel(o, .5, 3)
    o.parent = parent
    return o

def text(name, body, loc, size, material, parent=None, back=False):
    c = bpy.data.curves.new(name, 'FONT')
    c.body = body
    c.align_x = 'CENTER'
    c.size = size
    c.extrude = .025
    c.space_character = 1.2
    o = bpy.data.objects.new(name, c)
    scene.collection.objects.link(o)
    o.location = loc
    o.rotation_euler = (-math.pi/2, 0, math.pi) if back else (math.pi/2, 0, 0)
    applymat(o, material)
    if parent:
        o.parent = parent
    return o

def screw(name, x, y, z, parent=None):
    o = cyl(name, 1.85, .75, (x,y,z), silver, 'Y', parent, 32)
    slot = box(name+' slot', (1.7,.2,.42), (x,y+.42,z), black, .1, parent)
    return o, slot

# Thick speaker plinth: one retained circular donor speaker, horizontal and upward-facing.
base = box('Speaker plinth | removable shell', (242,146,57), (0,1,32.5), navy, 13)
box('Plinth lower reveal', (230,136,4), (0,1,6), black, 1.8)
for x in [-87,87]:
    for y in [-46,47]:
        cyl('Rubber isolation foot', 12, 5, (x,y,3), black)
grille = box('Removable wraparound acoustic grille', (244,148,37), (0,-.3,37), fabric, 12)
topgrille = box('Upward speaker outlet | fabric top', (226,130,3), (0,-1,62), fabric, 1.4)
box('Base rear service spine', (168,7,42), (0,71,33), navy, 4)
text('Base Echo wordmark', 'e c h o', (0,-72.7,26), 8, mint)

# Realistic serviceable head, held above the upward-facing speaker grille.
for x in [-86,86]:
    support = box('Isolated rear support', (17,32,43), (x,40,75), navy, 5)
    support.rotation_euler[0] = math.radians(-12)
    box('Support rubber joint', (18,30,3), (x,39,58), black, 1)
bpy.ops.object.empty_add(type='PLAIN_AXES', location=(0,26,159))
head = bpy.context.object
head.name = 'Display assembly | 12 degree rear tilt'
head.rotation_euler[0] = math.radians(-12)
body = frame('Vented display surround', (230,154,12), (216,140,8), 42, 1, navy, head)
rear = box('REMOVABLE | rear service cover', (225,5,149), (0,23.4,0), navy_light, 9, head)
woodframe = frame('Warm wood front trim', (230,154,12), (208,127,5), 5, -22, wood, head)
box('Screen black glass bezel', (210,2,130), (0,-22.3,-1), glass, 4, head)
box('Display panel | depth envelope', (212,6,132), (0,-16,-1), black, 3, head)

# Image texture maps 1:1 to the active screen aspect ratio.
verts = [(-99,-23.6,-60), (99,-23.6,-60), (99,-23.6,56.0156), (-99,-23.6,56.0156)]
mesh = bpy.data.meshes.new('Screen image mesh')
mesh.from_pydata(verts, [], [(0,1,2,3)])
mesh.uv_layers.new()
for lp, uv in zip(mesh.uv_layers.active.data, [(0,0),(1,0),(1,1),(0,1)]):
    lp.uv = uv
screen = bpy.data.objects.new('Echo | actual synthetic dashboard', mesh)
scene.collection.objects.link(screen)
screen.parent = head
m = bpy.data.materials.new('Echo dashboard | packed screenshot')
m.use_nodes = True
n, l = m.node_tree.nodes, m.node_tree.links
shader = n.get('Principled BSDF')
im = n.new('ShaderNodeTexImage')
im.image = bpy.data.images.load(str(UI))
im.image.pack()
l.new(im.outputs['Color'], shader.inputs['Base Color'])
l.new(im.outputs['Color'], shader.inputs['Emission Color'])
shader.inputs['Emission Strength'].default_value = .85
shader.inputs['Roughness'].default_value = .25
shader.inputs['Specular IOR Level'].default_value = .15
applymat(screen, m)

# CSI camera pod accommodates a case; shutter is a proposed enclosure feature.
box('IMX519 camera | protective top pod', (36,28,24), (0,-2,84), navy, 6, head)
box('Camera inset face', (29,1.3,17), (0,-16.2,85), black, 3, head)
cyl('Camera lens rim', 6, 2, (-4,-17.7,85), silver, 'Y', head)
cyl('Camera optical glass', 4.9, 1, (-4,-18.9,85), glass, 'Y', head)
optics = mat('Lens optical coating', (.016,.072,.081), .08, .35)
cyl('Camera optical reflection', 2.7, .2, (-4,-19.5,85), optics, 'Y', head)
box('Proposed sliding camera cover | open', (9,2.3,15), (9,-18,85), navy_light, 2, head)
for x in [7,9,11]:
    box('Shutter finger grip', (.4,.3,7), (x,-19.35,85), silver, .1, head)
for x in [-88,-85,-82,-79]:
    cyl('Separate USB mic acoustic opening', .58, .5, (x,-24.65,68), black, 'Y', head, 20)
text('Chin identification', 'E C H O  D E C K', (0,-24.6,-70), 3.4, silver, head)

# Rear vents are visual recesses; the final part requires measured cutouts and baffles.
coverparts = [rear]
for x in [-86,-78,-70,-62,-54,54,62,70,78,86]:
    for z in [-43,-31,-19,-7,5,17,29,41]:
        vent = box('Rear ventilation slot | concept', (3.6,.5,8), (x,26.05,z), black, 1.4, head)
        coverparts.append(vent)
badge = text('Rear name', 'ECHO DECK', (0,26.15,25), 5.8, silver, head, back=True)
coverparts.append(badge)
badge = text('Rear descriptor', 'SMART DISPLAY + SPEAKER', (0,26.15,14), 2.1, silver, head, back=True)
coverparts.append(badge)
for x in [-99,99]:
    for z in [-62,62]:
        coverparts.extend(screw('Rear captive screw',x,26.2,z,head))
portplate = box('Rear cable/service bay', (85,1.4,14), (0,26.5,-49), black, 3, head)
coverparts.append(portplate)
for xx, ww, hh in [(-30,11,4),(-5,13,7),(15,13,7),(34,13,9)]:
    coverparts.append(box('Provisional port access', (ww,.6,hh), (xx,27.3,-49), silver, 1, head))
    coverparts.append(box('Port interior', (ww-1,.8,hh-1), (xx,27.7,-49), black, .7, head))
# Visible external power lead, exits at the base to avoid loading the panel.
box('Rear power cable strain relief', (13,12,9), (-66,76,20), black, 3)
curve('External Pi power cable', [(-66,79,20),(-67,99,12),(-44,130,3),(39,152,2.5),(95,195,2.5)], 2.1, black)

# Simplified internal envelopes, visible only with covers removed.
internals = []
pi = box('Pi 4B | standard 85 x 56 board outline', (85,2,56), (-33,2,0), pcb, 1, head)
internals.append(pi)
for x in [-65,0]:
    for z in [-23,23]:
        internals.append(cyl('Pi standoff | illustrative location',2,7,(x,-2,z),copper,'Y',head,24))
for x,z,w,h in [(-45,3,16,16),(-20,4,13,13),(-44,-17,10,8)]:
    internals.append(box('Pi package', (w,3,h),(x,5,z),black,.6,head))
for i in range(7):
    internals.append(box('Pi cooling fin',(1.2,8,18),(-52+i*2.3,10,3),silver,.3,head))
for z in [-20,0,20]:
    internals.append(box('Pi USB/Ethernet envelope',(18,15,14),(10,10,z),silver,.9,head))
internals.append(box('Pi GPIO header',(48,6,4),(-39,7,22),black,.6,head))
for i in range(20):
    internals.append(cyl('GPIO reference pin',.35,3,(-60+i*2.3,11,22),copper,'Y',head,12))
internals.append(box('USB audio board | provisional envelope',(42,2,32),(65,3,-16),darkpcb,1,head))
internals.append(box('USB audio codec',(10,3,10),(65,6,-14),black,.3,head))
for x in [51,78]:
    internals.append(box('Audio connector',(8,7,6),(x,7,-25),silver,.4,head))
internals.append(box('USB microphone | provisional envelope',(21,14,20),(-83,2,49),black,2,head))
internals.append(box('HDMI panel controller | provisional envelope',(146,2,20),(3,-5,-49),pcb,1,head))
internals.append(curve('Internal USB to audio',[(9,17,-18),(26,20,-31),(43,15,-17),(48,8,-17)],1.5,black,head))
internals.append(curve('Internal USB to microphone',[(10,16,18),(-4,18,48),(-53,16,52),(-78,7,49)],1.4,black,head))
internals.append(curve('CSI ribbon route | illustrative', [(-28,6,10),(-26,12,45),(-8,10,60),(0,7,83)],2,ribbon,head))
internals.append(curve('Speaker wire | internal route',[(73,8,-23),(83,5,-58),(86,0,-77)],.65,mint,head))
driverparts=[]
driverparts.append(cyl('Salvaged speaker acoustic housing | size approximate',54,24,(0,-7,35),black))
driverparts.append(cyl('Salvaged speaker flange',56,3,(0,-7,48),navy_light))
driverparts.append(cyl('Speaker surround',35,3,(0,-7,51),black))
bpy.ops.mesh.primitive_torus_add(major_radius=29,minor_radius=5,major_segments=96,minor_segments=24,location=(0,-7,53))
o=bpy.context.object;o.name='Speaker rubber surround';applymat(o,black);driverparts.append(o)
driverparts.append(cyl('Speaker diaphragm',25,2,(0,-7,52),navy_light))
bpy.ops.mesh.primitive_uv_sphere_add(segments=48,ring_count=24,radius=16,location=(0,-7,52))
o=bpy.context.object;o.name='Speaker dust cap';o.scale=(1,1,.25);applymat(o,black);driverparts.append(o)

# Studio, cameras, and repeatable renders.
ground = mat('Studio warm grey',(.68,.70,.69),.85)
box('Studio ground',(2500,2500,3),(0,0,-2.7),ground,.1)
def area(name, loc, energy, size, color):
    bpy.ops.object.light_add(type='AREA', location=loc)
    o=bpy.context.object;o.name=name;o.data.energy=energy;o.data.shape='DISK';o.data.size=size;o.data.color=color
    o.rotation_euler=(Vector((0,0,100))-o.location).to_track_quat('-Z','Y').to_euler()
area('Large softbox | key',(-320,-400,590),6500000,500,(1,.89,.76))
area('Large softbox | fill',(440,-80,360),4200000,450,(.75,.88,1))
area('Rear softbox',(-130,380,490),5500000,400,(.82,1,.97))
world = scene.world
world.use_nodes=True
world.node_tree.nodes.get('Background').inputs['Color'].default_value=(.65,.7,.75,1)
world.node_tree.nodes.get('Background').inputs['Strength'].default_value=.4
bpy.ops.object.camera_add(location=(360,-555,340))
cam=bpy.context.object
cam.name='Presentation camera'
scene.camera=cam
cam.data.type='ORTHO'
cam.data.ortho_scale=425
cam.data.clip_end=5000
cam.data.lens=48
def camera(loc, target=(0,8,126), scale=425):
    cam.location=loc
    cam.rotation_euler=(Vector(target)-cam.location).to_track_quat('-Z','Y').to_euler()
    cam.data.ortho_scale=scale
def render(name):
    scene.render.filepath=str(OUT / name)
    print('Rendering '+name, flush=True)
    bpy.ops.render.render(write_still=True)

def save_public_model():
    # Blender retains source paths in packed-file records and file-browser state.
    for image in bpy.data.images:
        if image.source == 'FILE':
            image.filepath = '//reference/display-home.png'
            for packed in image.packed_files:
                packed.filepath = '//reference/display-home.png'
    for screen in bpy.data.screens:
        for area in screen.areas:
            for space in area.spaces:
                if space.type == 'FILE_BROWSER' and space.params:
                    space.params.directory = b'//'
    scene.render.filepath = '//preview/echo-deck-front.png'
    scene.render.use_stamp = False
    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(ROOT/'echo-deck-concept.blend'),
                              compress=False, relative_remap=False)

camera((340,-590,320))
save_public_model()
render('echo-deck-front.png')
camera((370,570,350), (0,15,126),435)
render('echo-deck-rear.png')
# A service study is a separate view of the same geometry, not an extra design.
for o in coverparts:
    o.hide_render=True
base.hide_render=True
grille.hide_render=True
topgrille.hide_render=True
camera((345,610,425),(0,8,120),435)
render('echo-deck-service.png')
for o in coverparts:
    o.hide_render=False
base.hide_render=False
grille.hide_render=False
topgrille.hide_render=False
camera((340,-590,320))
save_public_model()
print('CONCEPT COMPLETE',flush=True)
