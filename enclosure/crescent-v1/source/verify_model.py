from pathlib import Path
import json,math,sys,os
import numpy as np,trimesh
import build_print_model as b

P=b.OUT
checks={}
for f in sorted((P/'STL').glob('*.stl')):
    m=trimesh.load_mesh(f)
    checks[f.stem]={'watertight_after_STL_reload':bool(m.is_watertight),'winding_consistent':bool(m.is_winding_consistent),'components':len(m.split(only_watertight=False)),'volume_ml':float(m.volume/1000),'minimum_z':float(m.bounds[0,2])}
    assert m.is_watertight and m.is_winding_consistent and len(m.split())==1,f.name

head=b.carrier()
for angle in [-34,34]:head-=b.polar(b.box((13,3.8,5.8),(27.4,0,-9)),angle)
ring=b.retainer();button=b.plunger();keeper=b.button_keeper()
def overlap(a,c):return round((a^c).volume(),8)
checks['assembly_intersections_mm3']={'ring_with_carrier':overlap(head,ring),
    'plunger_rest_with_carrier':max(overlap(head,b.polar(button,x)) for x in [-34,34]),
    'plunger_fully_pressed_with_carrier':max(overlap(head,b.polar(button.translate((-.44,0,0)),x)) for x in [-34,34]),
    'plunger_outward_stop_with_carrier':max(overlap(head,b.polar(button.translate((.44,0,0)),x)) for x in [-34,34]),
    'keeper_with_carrier':max(overlap(head,b.polar(keeper,x)) for x in [-34,34]),
    'keeper_with_plunger':overlap(keeper,button)}
print(checks['assembly_intersections_mm3'],flush=True)
for k,v in checks['assembly_intersections_mm3'].items():assert v<.002,(k,v)
# Generic straight USB connector envelope, conservative versus earlier render.
plug=b.roundbox((16,10,7),(-31.8,0,-8.07),.6)
checks['USB_plug_clearance_intersection_mm3']=overlap(b.arm(),b.headworld(plug))
assert checks['USB_plug_clearance_intersection_mm3']<.002
checks['USB_insertion_path_mm3']={str(dx):overlap(b.arm(),b.headworld(plug.translate((-dx,0,0)))) for dx in [0,2,4,6]}
checks['arm_with_retainer_intersection_mm3']=overlap(b.arm(),b.headworld(ring))
assert checks['arm_with_retainer_intersection_mm3']<.002
# Verify actual manufacturer solids against the local carrier and retainer.
import cadquery as cq
reference=os.environ.get('WAVESHARE_STEP')
if not reference:
    raise SystemExit('Set WAVESHARE_STEP to the original vendor ESP32-S3-Touch-AMOLED-1_75.stp file')
src=Path(reference).expanduser().resolve(strict=True)
ss=cq.importers.importStep(str(src)).val().Solids()
collisions=[];skipped=[];count=0;button_contacts=[];insertion=[]
for i,s in enumerate(ss):
    bb=s.BoundingBox()
    radial_max=max(math.hypot(x,z) for x in [bb.xmin,bb.xmax] for z in [bb.zmin,bb.zmax])
    if radial_max<22.4 and i not in [277,278]:continue
    s=s.rotate((0,0,0),(1,0,0),90).translate((0,0,-2.77))
    verts,faces=s.tessellate(.015,.08)
    tm=trimesh.Trimesh([v.toTuple() for v in verts],faces,process=True)
    try:m=b.frommesh(tm)
    except Exception as e:skipped.append([i,str(e)]);continue
    if m.status().name!='NoError':skipped.append([i,str(m.status())]);continue
    count+=1
    v=overlap(m,head);vr=overlap(m,ring)
    vp=max(overlap(m,b.polar(button,a)) for a in [-34,34])
    vk=max(overlap(m,b.polar(keeper,a)) for a in [-34,34])
    if v>.002 or vr>.002 or vp>.002 or vk>.002:collisions.append({'solid':i,'carrier':v,'ring':vr,'rest_button':vp,'keeper':vk})
    worst=(0,0)
    for dz in np.arange(.5,13,.5):
        vol=overlap(m.translate((0,0,float(dz))),head)
        if vol>worst[0]:worst=(vol,float(dz))
    if worst[0]>.002:insertion.append({'solid':i,'max_intersection_mm3':worst[0],'z_offset_mm':worst[1]})
    if i in [277,278]:
        angle=-34 if i==277 else 34
        button_contacts.append({'solid':i,'rest_overlap':overlap(m,b.polar(button,angle)),
            'pressed_overlap':overlap(m,b.polar(button.translate((-.44,0,0)),angle))})
checks['manufacturer_CAD_check']={'solids_in_STEP':len(ss),'boundary_solids_checked':count,'interferences':collisions,'front_loading_path_interferences':insertion,'failed_solid_conversions':skipped,'button_contact_check':button_contacts,'method':'Exact source BRep tessellated at 0.015 mm, Manifold volume intersections; interior solids outside enclosure contact region excluded by conservative bounding boxes. Front-loading path sampled every 0.5 mm over 12.5 mm.'}
(P/'verification.json').write_text(json.dumps(checks,indent=2))
print(json.dumps(checks,indent=2))
assert not collisions,'Hardware collision(s); see verification.json'
assert not skipped,'Reference solids could not be checked'
assert not insertion,'Front insertion blocked; see verification.json'
assert max(checks['USB_insertion_path_mm3'].values())<.002,'USB insertion path blocked'
