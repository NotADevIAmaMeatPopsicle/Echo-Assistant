"""Change Wi-Fi through a verified USB board on an explicitly chosen SSH host.

Retains the live remote host TLS pairing. Secrets travel through encrypted stdin;
they are neither command-line arguments nor files on the USB host.
"""
import argparse
import getpass
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from backend import deployment
import backend.remote_host as remote
from backend.transport import load_wifi, MAC
from tools.remote_device import client

SCRIPT = r'''
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$config=[Console]::In.ReadToEnd()|ConvertFrom-Json
if ($config.port -notmatch '^COM[0-9]+$' -or $config.mac -notmatch '^[0-9a-f]{2}(:[0-9a-f]{2}){5}$') { throw 'Invalid USB target' }
$boards=@(Get-CimInstance Win32_PnPEntity | Where-Object { $_.DeviceID -ieq ('USB\VID_303A&PID_1001\'+$config.mac) -and $_.Status -eq 'OK' })
$ports=@(Get-CimInstance Win32_PnPEntity | Where-Object { $_.Name -eq ('USB Serial Device ('+$config.port+')') -and $_.DeviceID -like 'USB\VID_303A&PID_1001&MI_00\*' -and $_.Status -eq 'OK' })
if ($boards.Count -ne 1 -or $ports.Count -ne 1) { throw 'Expected USB board is absent' }
$parent=(Get-PnpDeviceProperty -InstanceId $ports[0].DeviceID -KeyName 'DEVPKEY_Device_Parent').Data
if ($parent -ine $boards[0].DeviceID) { throw 'USB port does not belong to the paired board' }
$serial=New-Object System.IO.Ports.SerialPort
$serial.PortName=$config.port; $serial.BaudRate=115200
$serial.DtrEnable=$false; $serial.RtsEnable=$false
$serial.ReadTimeout=200; $serial.WriteTimeout=1000
$serial.NewLine="`n"
function Send-Pair($command,$expected) {
    $serial.WriteLine($command)
    $deadline=[DateTime]::UtcNow.AddSeconds(4)
    while ([DateTime]::UtcNow -lt $deadline) {
        try { $line=$serial.ReadLine().Trim() } catch [TimeoutException] { continue }
        if ($line -eq $expected) { return }
        if ($line.StartsWith('PAIR_ERROR')) { throw 'Device rejected pairing; no secret output' }
    }
    throw 'USB pairing acknowledgement timed out'
}
try {
    $serial.Open()
    Send-Pair 'PAIR_BEGIN' 'PAIR_OK BEGIN'
    Send-Pair ('PAIR_SSID '+[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($config.ssid))) 'PAIR_OK FIELD'
    Send-Pair ('PAIR_WIFI '+[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($config.password))) 'PAIR_OK FIELD'
    Send-Pair ('PAIR_HOST '+$config.host) 'PAIR_OK FIELD'
    Send-Pair ('PAIR_KEY '+$config.key) 'PAIR_OK FIELD'
    Send-Pair 'PAIR_SAVE' 'PAIR_OK SAVED'
    [Console]::Out.Write('{"saved":true,"rebooting":true}')
} finally {
    if ($serial.IsOpen) { $serial.Close() }; $serial.Dispose()
    $config.password=$null; $config.key=$null
}
'''

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--usb-host', required=True)
    parser.add_argument('--port', required=True)
    parser.add_argument('--ssid', required=True)
    parser.add_argument('--wifi-secrets', type=Path, help='Read password from an existing ESPHome YAML, without modifying it')
    args = parser.parse_args()
    if args.usb_host.startswith('-') or not re.fullmatch(r'[A-Za-z0-9_.@-]+', args.usb_host) or not re.fullmatch(r'COM[0-9]+', args.port):
        raise ValueError('Invalid USB host or port')
    if not re.fullmatch(r'[0-9a-f]{2}(:[0-9a-f]{2}){5}', MAC):
        raise ValueError('Set ECHO_DEVICE_MAC to your verified board identity')
    pairing = load_wifi(ROOT)
    if not pairing: raise ValueError('Existing host pairing is required')
    code = "import json,hashlib; from pathlib import Path; d=json.loads(Path('/opt/echo/local/wifi.json').read_text()); print(hashlib.sha256(d['key'].encode()).hexdigest())"
    check = subprocess.run(['docker', '--context', deployment.docker_context(), 'exec', 'echo-api', 'python', '-c', code],
                           capture_output=True, text=True, check=True)
    if check.stdout.strip() != hashlib.sha256(pairing['key'].encode()).hexdigest():
        raise ValueError('Local pairing differs from the live server')
    with client() as api:
        response=api.get('/v1/voice');response.raise_for_status();state=response.json()
        if state.get('status') not in {'armed','muted','cooldown','connecting','disconnected'}:
            raise ValueError('Wait until Echo finishes the current interaction')
    if args.wifi_secrets:
        import yaml
        password = yaml.safe_load(args.wifi_secrets.read_text())['wifi_password']
    else:
        password = getpass.getpass('Wi-Fi password (hidden): ')
    if not 1<=len(args.ssid.encode())<=32 or not isinstance(password,str) or not 8<=len(password.encode())<=63 or '\0' in password+args.ssid:
        raise ValueError('Invalid Wi-Fi credentials')
    data = {'port':args.port,'ssid':args.ssid,'password':password,'host':pairing['host'],'key':pairing['key'],'mac':MAC}
    remote.HOST = args.usb_host
    result = json.loads(remote._powershell(SCRIPT,json.dumps(data).encode(),timeout=35))
    print(json.dumps({'usb_host':args.usb_host,'port':args.port,'ssid':args.ssid,**result}))

if __name__ == '__main__':
    try: main()
    except Exception as error:
        raise SystemExit('Wi-Fi pairing did not complete ('+type(error).__name__+'). No secrets printed.') from None
