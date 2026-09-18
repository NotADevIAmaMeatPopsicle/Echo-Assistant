from pathlib import Path
import json,math,numpy as np,trimesh
from scipy.spatial.transform import Rotation
import build_print_model as b

P=b.OUT
main=trimesh.load_mesh(P/'STL'/'01_Crescent_main_stand.stl')
pts=main.convex_hull.vertices
best=[]
for rx in range(-50,51,10):
    for ry in range(25,71,5):
        for rz in range(0,180,5):
            rot=Rotation.from_euler('xyz',[rx,ry,rz],degrees=True).as_matrix()
            v=pts@rot.T; ext=np.ptp(v,axis=0)
            # Leave >= 4 mm per side for a compact raft/support envelope on this shallow plate.
            if ext[0]>215.64 or ext[1]>118.48 or ext[2]>210:continue
            # Avoid placing the screen face parallel to the build plate.
            normal=rot@np.array([0,-math.sin(math.radians(78)),math.cos(math.radians(78))])
            face_angle=math.degrees(math.acos(min(1,abs(normal[2]))))
            if face_angle<30 or face_angle>78:continue
            score=ext[2]+.17*ext[0]+.6*ext[1]
            best.append((score,[rx,ry,rz],ext.tolist(),face_angle))
assert best,'No orientation fits support margins'
best.sort();chosen=best[0]
orientations={}
for path in sorted((P/'STL').glob('*.stl')):
    m=trimesh.load_mesh(path)
    if path.stem.startswith('01_'):angles=chosen[1]
    elif path.stem.startswith(('02_','09_','GAUGE')):angles=[22,0,0]
    elif path.stem.startswith(('06_','07_','08_')):angles=[15,0,0]
    else:angles=[25,0,0]
    mat=Rotation.from_euler('xyz',angles,degrees=True).as_matrix()
    tf=np.eye(4);tf[:3,:3]=mat;m.apply_transform(tf)
    shift=np.array([-m.bounds[:,0].mean(),-m.bounds[:,1].mean(),4-m.bounds[0,2]])
    m.apply_translation(shift)
    out=P/'M7-oriented'/(path.stem+'_M7.stl');m.export(out)
    check=trimesh.load_mesh(out)
    assert check.is_watertight and check.extents[0]<223.64 and check.extents[1]<126.48 and check.bounds[1,2]<230,out
    orientations[path.stem]={'rotation_xyz_deg':angles,'bbox_mm':np.round(check.extents,3).tolist(),'bottom_z_mm':round(float(check.bounds[0,2]),4),'top_z_mm':round(float(check.bounds[1,2]),4),'supports_included':False}
report={'printer':'Anycubic Photon Mono M7','build_volume_mm':[223.64,126.48,230],'main_selection':chosen,'oriented_parts':orientations,'warning':'Oriented STLs are raised 4 mm for slicer-generated supports. They are not sliced printer jobs. Do not print floating unsupported geometry.'}
(P/'M7-orientation.json').write_text(json.dumps(report,indent=2))
(P/'source'/'prepare_m7.py').write_text(Path(__file__).read_text())
print(json.dumps(report,indent=2))
