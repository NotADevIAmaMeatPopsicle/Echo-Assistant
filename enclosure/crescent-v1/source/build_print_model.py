"""Manufacturing meshes for the selected Crescent concept, in millimetres.

Requires numpy, trimesh, manifold3d. STEP reference inspection uses CadQuery separately.
All final parts are Boolean solids; illustrative electronics are never exported as print parts.
"""
from pathlib import Path
import math, json, hashlib
import numpy as np
import trimesh
from manifold3d import Manifold as M, CrossSection as C, Mesh64, OpType

HERE=Path(__file__).resolve().parent
OUT=HERE.parent if HERE.name=='source' else HERE.parents[1]/'crescent-print-ready-v1'
STL=OUT/'STL';ASSEM=OUT/'assembly-reference'
for p in [OUT,STL,ASSEM,OUT/'source',OUT/'M7-oriented']:p.mkdir(parents=True,exist_ok=True)
N=256
HEAD=(0,4,112)
PARTS={};PLACEMENTS=[]

def uni(*parts):return M.batch_boolean(list(parts),OpType.Add)
def box(d,p=(0,0,0)):return M.cube(d,True).translate(p)
def cyl(r,h,p=(0,0,0),r2=-1,n=N):return M.cylinder(h,r,r2,n,True).translate(p)
def ann(ro,ri,h,z=0):return cyl(ro,h,(0,0,z))-cyl(ri,h+2,(0,0,z))
def sector(ro,ri,a,b,h,z=0):
    theta=np.linspace(math.radians(a),math.radians(b),max(4,int((b-a)*1.3)+1))
    pts=[[ro*math.cos(t),ro*math.sin(t)] for t in theta]+[[ri*math.cos(t),ri*math.sin(t)] for t in theta[::-1]]
    return C([pts]).extrude(h).translate((0,0,z-h/2))
def roundbox(d,p=(0,0,0),r=.8):
    x,y,z=d
    cross=C.square((x-2*r,y-2*r),True).offset(r,circular_segments=24)
    return cross.extrude(z).translate((p[0],p[1],p[2]-z/2))
def slot(length,width,h,p=(0,0,0)):
    return uni(box((max(.01,length-width),width,h)),cyl(width/2,h,(-(length-width)/2,0,0),n=64),cyl(width/2,h,((length-width)/2,0,0),n=64)).translate(p)
def hexhole(flat,h,p=(0,0,0)):return cyl(flat/math.sqrt(3),h,p,n=6).rotate((0,0,30))
def headworld(s):return s.rotate((78,0,0)).translate(HEAD)
def hp(p):
    x,y,z=p;a=math.radians(78)
    return np.array((x,4+y*math.cos(a)-z*math.sin(a),112+y*math.sin(a)+z*math.cos(a)))
def polar(s,a):return s.rotate((0,0,a))
def mesh(s):
    raw=s.simplify(.0001).to_mesh64()
    return trimesh.Trimesh(vertices=np.asarray(raw.vert_properties)[:,:3],faces=np.asarray(raw.tri_verts),process=True)
def frommesh(m):
    m=trimesh.Trimesh(m.vertices,m.faces,process=True)
    if m.volume<0:m.invert()
    return M(Mesh64(np.asarray(m.vertices,dtype=np.float64),np.asarray(m.faces,dtype=np.uint64)))
def register(name,s,qty=1,description='',assembly=None):
    if s.status().name!='NoError':raise RuntimeError((name,s.status()))
    m=mesh(s)
    if not m.is_watertight or not m.is_winding_consistent or m.volume<=0:raise RuntimeError('Invalid mesh '+name)
    comps=m.split(only_watertight=False)
    if len(comps)!=1:raise RuntimeError(f'{name} has {len(comps)} disconnected bodies: {[x.volume for x in comps]}')
    m.export(ASSEM/(name+'.stl'))
    local=m.copy();local.apply_translation(-np.array([0,0,local.bounds[0,2]]));local.export(STL/(name+'.stl'))
    PARTS[name]={'quantity':qty,'description':description,'volume_ml':round(m.volume/1000,3),'triangles':len(m.faces),'bounds_mm':np.round(local.extents,3).tolist(),'watertight':bool(local.is_watertight),'components':len(comps),'sha256':hashlib.sha256((STL/(name+'.stl')).read_bytes()).hexdigest()}
    if assembly is not None:PLACEMENTS.extend([{'part':name,**p} for p in assembly])
    print(name,PARTS[name]['volume_ml'],'ml',local.extents,flush=True)

def carrier(pocket=25.1,buttons=True):
    # Front glass at local z=0. Manufacturer's peripheral glass underside is z=-1.10.
    body=ann(27.3,pocket,10.25,-5.275)
    # Entry chamfer: 0.45 mm wider at the front, gentle drop-in rather than interference.
    body-=cyl(pocket,.5,(0,0,-.40),r2=pocket+.45)
    # Supported side arcs; north/south relief clears the display's two projecting tabs.
    ledges=uni(sector(pocket+.15,23.3,-58,58,1.25,-1.975),sector(pocket+.15,23.3,122,238,1.25,-1.975))
    # The USB socket projects beyond the PCB edge. Its installation path must pass the seat.
    ledges-=sector(26.0,23.1,165,195,3.0,-1.975)
    body=uni(body,ledges)
    # Retainer's small radial beads engage a shallow outer groove.
    body-=ann(28,27.0,1.4,-2.20)
    # Socket lies at x=-23.79, y~=0, z=-8.07; cavity is open to the rear.
    body-=box((10,12.4,8),(-26.0,0,-9.8))
    if buttons:
        for angle in [-34,34]:body=uni(body,polar(button_guide(),angle))
    return body

def button_guide():
    # Coordinates: X is radial outward. Plunger has 0.90 mm total limited travel.
    guide=roundbox((8.0,14.8,7.2),(28.5,0,-7.8),.65)
    # Rear-loading channel; its front and side walls remain attached to carrier.
    guide-=box((13.0,3.8,5.8),(27.4,0,-9.0))
    guide-=box((2.3,6.0,5.8),(30.0,0,-9.0))
    # Stem reaches the switch through the carrier wall.
    guide-=box((6.0,3.8,5.8),(23.2,0,-9.0))
    # Two M2 through bolts and front-access captive nuts hold the rear keeper.
    for y in [-5.3,5.3]:
        guide-=cyl(1.2,12,(28.5,y,-7.8),n=64)
        guide-=cyl(2.6,2.7,(28.5,y,-5.45),n=6)
    return guide

def plunger():
    # Inner face 22.98; switch envelope's faces are 22.792 and 22.849.
    stem=roundbox((10.32,3.0,2.8),(28.14,0,-7.8),.25)
    flange=roundbox((1.4,5.2,2.8),(30.0,0,-7.8),.25)
    cap=roundbox((1.4,6.4,5.6),(33.7,0,-7.8),.5)
    # The inner end contacts the switch actuator; the flange limits travel.
    return uni(stem,flange,cap)

def button_keeper():
    keeper=roundbox((8.2,14.6,1.8),(28.5,0,-12.3),.7)
    keeper=uni(keeper,roundbox((8.0,3.4,2.0),(28.5,0,-10.45),.25))
    for y in [-5.3,5.3]:keeper-=cyl(1.2,4,(28.5,y,-12.3),n=64)
    return keeper

def retainer(bead=27.08):
    # Full flange stops at r=27.0. Three separated circumferential fingers flex radially.
    s=ann(27.0,22.8,1.5,.9)
    # Underside lead-in/edge break on the screen-facing aperture.
    s-=cyl(23.05,.35,(0,0,.20),r2=22.8)
    for start in [-130,-10,110]:
        end=start+40
        beam=sector(28.5,27.5,start,end,5.15,-.925)
        root=sector(28.5,26.65,start,start+5.0,1.5,.9)
        # Root widens gradually over 5 degrees; rounded inner corner eases the flex transition.
        a=math.radians(start+5)
        root=uni(root,cyl(.65,1.5,(27.3*math.cos(a),27.3*math.sin(a),.9),n=32))
        beadprofile=C([[[27.50,-3.25],[27.70,-3.25],[27.70,-1.70],[27.50,-1.70],[bead,-1.95],[bead,-2.22]]])
        catch=M.revolve(beadprofile,256,5).rotate((0,0,end-6))
        s=uni(s,beam,root,catch)
    a=math.radians(-65)
    s-=cyl(2.6,4,(26.8*math.cos(a),26.8*math.sin(a),.9),n=64)
    return s

def base_frame():
    ring=ann(55,44,5,6.5).translate((0,-5,0))
    # Through arc slots permit angular positioning of the four speaker arms.
    for a in [12,102,192,282]:ring-=sector(51.3,47.7,a,a+66,9,6.5).translate((0,-5,0))
    pieces=[ring]
    for x in [-30,30]:pieces.append(roundbox((6,30,5),(x,49,6.5),2))
    pieces.append(roundbox((66,6,5),(0,62,6.5),2))
    # Root pad spreads the arm load into both perimeter rails.
    pieces.append(cyl(9,6,(-45,23,6),n=96))
    for x,y in [(-35,-40),(35,-40),(-30,60),(30,60)]:pieces.append(cyl(4.8,5,(x,y,2.5),n=64))
    # Cross ties remain outside the speaker's acoustic opening.
    for x in [-30,30]:pieces.append(roundbox((6,23,3),(x,42,8),1))
    return uni(*pieces)

def battery_cradle():
    # Internal clear box 52.8 x 13.2, two open rails and a soft-strap route.
    parts=[]
    for x in [-27.3,27.3]:
        wall=roundbox((1.8,17.0,27.0),(x,55,22.5),.45)
        wall-=box((4,3.4,6),(x,55,32.0))
        parts.append(wall)
        for yy in [47.5,62.5]:parts.append(roundbox((4.4,1.8,24),(x-1.3*np.sign(x),yy,21),.4))
    for x in [-20,20]:parts.append(roundbox((6,17,2),(x,55,10),.7))
    parts.append(roundbox((55.5,2.0,5),(0,62.6,11.5),.6))
    # Front contact opening: only side guards, leaving the center 37 mm unobstructed.
    for x in [-23.5,23.5]:parts.append(roundbox((8,2.0,5),(x,47.4,11.5),.6))
    return uni(*parts)

def bezier(p0,p1,p2,p3,n):
    p0,p1,p2,p3=map(np.array,[p0,p1,p2,p3]);ts=np.linspace(0,1,n,endpoint=False)
    return [((1-t)**3*p0+3*(1-t)**2*t*p1+3*(1-t)*t*t*p2+t**3*p3) for t in ts]

def arm():
    port=hp((-31,0,-8.07));bendz=port[2]-19
    pts=bezier((-45,20,8),(-51,20,25),(-55,12,53),(-55,8,70),80)
    pts+=bezier((-55,8,70),(-55,6,80),(-55,5.6,bendz-4),(-55,5.6,bendz),40)
    for u in np.linspace(0,1,70,endpoint=False):
        a=math.pi-math.pi/2*u;yy=5.6-1.8*(u*u*(3-2*u))
        pts.append(np.array((-36+19*math.cos(a),yy,bendz+19*math.sin(a))))
    pts.extend(np.array((x,3.8,port[2])) for x in np.linspace(-36,-24.8,32))
    vs=[];fs=[]
    for i,p in enumerate(pts):
        t=pts[min(i+1,len(pts)-1)]-pts[max(i-1,0)];n=np.array((t[2],0,-t[0]));n/=np.linalg.norm(n)
        u=np.clip((p[2]-76)/29,0,1);u=u*u*(3-2*u)
        root=np.clip((32-p[2])/24,0,1);w=13+6.2*u+4*root;d=10+4*u;th=1.8+.5*root
        profile=[(-w/2,0),(w/2,0),(w/2,d),(w/2-th,d),(w/2-th,th),(-w/2+th,th),(-w/2+th,d),(-w/2,d)]
        for xx,yy in profile:vs.append(p+n*xx+np.array((0,yy+math.tan(math.radians(12))*n[2]*xx*u,0)))
    # Triangulate closed concave U ends using a proven polygon triangulation pattern.
    captris=[(0,1,4),(0,4,5),(1,2,3),(1,3,4),(0,5,6),(0,6,7)]
    fs.extend(tuple(reversed(t)) for t in captris)
    for i in range(len(pts)-1):
        for j in range(8):
            a=i*8+j;b=i*8+(j+1)%8;c=(i+1)*8+(j+1)%8;d=(i+1)*8+j
            fs.extend([(a,b,c),(a,c,d)])
    k=(len(pts)-1)*8;fs.extend(tuple(k+x for x in t) for t in captris)
    s=frommesh(trimesh.Trimesh(vs,fs,process=True))
    if s.status().name!='NoError':raise RuntimeError('Arm sweep '+str(s.status()))
    # Slotted side flanges accept 2.5 mm reusable ties; they don't break the front web.
    for zz,xx,yy in [(40,-52,18),(74,-55,8)]:
        s-=box((26,3.4,4.4),(xx,yy+6.5,zz))
    # Functional USB clearance at the junction, using the manufacturer's socket depth.
    s-=headworld(box((13,12.4,8),(-24.0,0,-9.8)))
    return s

def speaker_arm():
    p=roundbox((30,13,3.4),(-8,0,1.7),1.8)
    # One angular clamp at outer end, radial post slot inward.
    p-=cyl(1.8,6,(4,3,1.7),n=64)
    p-=slot(18,3.6,6,(-9,-2.8,1.7))
    return p

def speaker_post(pin=2.4):
    # Captive M3 nut is inserted sideways; pin is never a self-tapping resin screw.
    p=uni(cyl(4.8,9,(0,0,4.5),n=96),cyl(pin/2,3.5,(0,0,10.75),r2=pin/2-.15,n=64))
    p-=cyl(1.8,6,(0,0,2.5),n=64)
    p-=cyl(3.3,2.7,(0,0,3.15),n=6)
    p-=box((7.4,6.0,2.7),(2.5,0,3.15))
    return p

def spacer():return ann(4.8,1.8,4,2)

def fit_gauge(d):
    # A full circular bore with a lead-in. Keep each gauge with its named file.
    g=ann(d/2+2.6,d/2,2.5,1.25)
    g-=cyl(d/2+.35,.6,(0,0,2.35),r2=d/2,n=N)
    return g

def main():
    frame=base_frame();cradle=battery_cradle();a=arm();head=carrier()
    # Cut button channels through the carrier after joining guide bodies, so stems cannot jam in an uncut wall.
    for angle in [-34,34]:head-=polar(box((13,3.8,5.8),(27.4,0,-9)),angle)
    mainbody=uni(frame,cradle,a,headworld(head))
    # Diagnostic subassemblies are kept outside the slicer-import directory.
    for name,s in [('carrier-local',head),('arm-only',a),('base-only',frame),('cradle-only',cradle)]:mesh(s).export(ASSEM/(name+'.stl'))
    register('01_Crescent_main_stand',mainbody,1,'One-piece open stand: base, arm, screen carrier and battery cradle',assembly=[{'translation':[0,0,0],'rotation':[0,0,0]}])
    register('02_Screen_snap_ring',retainer(),1,'Three long low-deflection circumferential fingers; test cured resin first',assembly=[{'translation':list(HEAD),'rotation':[78,0,0]}])
    register('03_Button_plunger',plunger(),2,'Rigid radial plunger; rear-load before installing keepers',assembly=[{'translation':list(HEAD),'rotation':[78,0,0],'pre_z_rotation':ang} for ang in [-34,34]])
    register('04_Button_rear_keeper',button_keeper(),2,'M2-bolted rear keeper, two M2 nuts per button',assembly=[{'translation':list(HEAD),'rotation':[78,0,0],'pre_z_rotation':ang} for ang in [-34,34]])
    register('05_Speaker_adjustable_arm',speaker_arm(),4,'M3 angular clamp plus radial slot for locating post')
    register('06_Speaker_post_2p4mm',speaker_post(2.4),4,'2.4 mm tapered locating pin with side-loaded M3 nut')
    register('07_Speaker_post_2p0mm_OPTION',speaker_post(2.0),4,'Use instead of 06 if speaker holes require smaller pins')
    register('08_Speaker_height_spacer_4mm_OPTION',spacer(),4,'Optional 4 mm post lift; choose longer M3 screw if used')
    upper_arm=a^box((220,220,120),(0,0,149))
    fit_neck=uni(headworld(head),upper_arm).translate((0,-4,-112)).rotate((-78,0,0))
    register('09_Screen_carrier_FIT_TEST',fit_neck,1,'Screen carrier plus upper USB pocket; print with 02-04 first to check board, actual cable, ring and buttons')
    for d in [49.8,50.2,50.6]:register('GAUGE_'+str(d).replace('.','p')+'mm',fit_gauge(d),1,'Optional entry-clearance gauge; production carrier uses 50.2 mm bore')
    # Pure assembly metadata; never mistaken for a printable model.
    (OUT/'parts-manifest.json').write_text(json.dumps({'units':'mm','parts':PARTS,'assembly':PLACEMENTS,'nominal_resin_density_g_ml':1.1,'provisional_speaker':True},indent=2))
    (OUT/'source'/'build_print_model.py').write_text(Path(__file__).read_text())
    print('OUTPUT',OUT,flush=True)

if __name__=='__main__':main()
