"""Private camera producer. Frames live in a temporary RAM directory, never a recording."""
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def write(path, data):
    temporary = path.with_suffix('.new')
    temporary.write_bytes(data)
    temporary.replace(path)


def readers(device, producer):
    """A ready virtual webcam can show black while the physical sensor is off."""
    for process in Path('/proc').glob('[0-9]*'):
        if process.name in {str(os.getpid()), str(producer)}:
            continue
        try:
            for fd in (process / 'fd').iterdir():
                if os.readlink(fd) == device:
                    return True
        except OSError:
            continue
    return False


def lens_device():
    for p in Path('/sys/class/video4linux').glob('v4l-subdev*/name'):
        if 'ak7375' in p.read_text().lower():
            return '/dev/' + p.parent.name
    return None


def main(directory):
    import numpy as np
    from picamera2 import Picamera2
    from PIL import Image
    root = Path(directory)
    camera, output = None, None
    lens = lens_device()
    running = True
    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, stop)
    state = {'capturing': False, 'ready': False, 'motion_at': 0, 'focus': None,
             'focus_supported': bool(lens), 'focusing': False, 'error': None}
    applied_focus = None
    previous = None
    motion_count = 0
    focus_request = None
    sweep, scores = [], []
    next_frame = 0
    last_status = 0
    def focus(value):
        if lens:
            subprocess.run(['v4l2-ctl', '-d', lens, '--set-ctrl=focus_absolute=' + str(value)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2, check=True)
            state['focus'] = value
    try:
        while running:
            control = json.loads((root / 'control.json').read_text())
            if time.monotonic() - control.get('heartbeat', 0) > 12:
                break
            virtual = control['purpose'] in {'call', 'meet'}
            if virtual and output is None:
                output = subprocess.Popen(['ffmpeg', '-y', '-nostdin', '-loglevel', 'error', '-threads', '1', '-f', 'rawvideo',
                    '-pixel_format', 'rgb24', '-video_size', '640x360', '-framerate', '10', '-i', 'pipe:0',
                    '-an', '-c:v', 'rawvideo', '-threads', '1', '-pix_fmt', 'yuv420p', '-f', 'v4l2', '/dev/video42'],
                    stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            want_capture = not virtual or readers('/dev/video42', output.pid)
            if want_capture and camera is None:
                camera = Picamera2()
                camera.configure(camera.create_video_configuration(
                    main={'size': (640, 360), 'format': 'BGR888'}, buffer_count=4,
                    controls={'FrameRate': 10}))
                camera.start()
                state['capturing'] = True
                previous = None
            elif not want_capture and camera is not None:
                camera.stop(); camera.close(); camera = None
                state['capturing'] = False
                (root / 'frame.jpg').unlink(missing_ok=True)
            if camera is not None:
                array = camera.capture_array('main')
                if control.get('rotate') == 180:
                    array = np.rot90(array, 2)
                if control.get('mirror'):
                    array = array[:, ::-1]
                array = np.ascontiguousarray(array)
                sample = array[::8, ::8].mean(axis=2).astype(np.float32)
                if lens and control.get('focus') != applied_focus:
                    applied_focus = control.get('focus')
                    if applied_focus is not None:
                        focus(applied_focus)
                if lens and control.get('focus_once') != focus_request:
                    focus_request = control.get('focus_once')
                    if focus_request:
                        sweep = list(range(0, 4096, 256)); scores = []
                        state['focusing'] = True
                if sweep:
                    position = sweep.pop(0)
                    focus(position)
                    camera.capture_array('main')
                    focused = camera.capture_array('main')[::4, ::4].mean(axis=2).astype(np.float32)
                    score = float(np.mean(np.diff(focused, axis=0)**2) + np.mean(np.diff(focused, axis=1)**2))
                    scores.append((score, position))
                    if not sweep:
                        focus(max(scores)[1]); state['focusing'] = False
                        state['focus_completed'] = focus_request
                if previous is not None and control['purpose'] == 'presence':
                    difference = sample - previous
                    difference -= np.median(difference)
                    movement = float(np.mean(np.abs(difference) > 18)) > 0.05
                    motion_count = motion_count + 1 if movement else 0
                    if motion_count >= 2:
                        state['motion_at'] = time.time()
                previous = sample
                if control['purpose'] != 'presence':
                    buf = io.BytesIO(); Image.fromarray(array).save(buf, 'JPEG', quality=75)
                    write(root / 'frame.jpg', buf.getvalue())
            else:
                array = np.zeros((360, 640, 3), dtype=np.uint8)
            if output:
                if output.poll() is not None:
                    raise RuntimeError('Virtual camera stopped')
                output.stdin.write(array.tobytes()); output.stdin.flush()
            state['ready'] = True
            state['updated_at'] = time.time()
            if time.monotonic() - last_status > .4:
                write(root / 'status.json', json.dumps(state).encode()); last_status = time.monotonic()
            interval = .4 if control['purpose'] == 'presence' else .1
            next_frame = max(next_frame + interval, time.monotonic())
            time.sleep(max(0, next_frame - time.monotonic()))
    finally:
        if camera:
            camera.stop(); camera.close()
        if output:
            output.terminate()
            try: output.wait(timeout=2)
            except subprocess.TimeoutExpired: output.kill(); output.wait()
        (root / 'frame.jpg').unlink(missing_ok=True)
        state.update(capturing=False, ready=False)
        write(root / 'status.json', json.dumps(state).encode())


if __name__ == '__main__':
    try:
        main(sys.argv[1])
    except Exception:
        write(Path(sys.argv[1]) / 'status.json', json.dumps({'capturing': False, 'ready': False,
            'error': 'Camera could not start. Check the camera connection and virtual webcam driver.'}).encode())
        raise SystemExit(1) from None
