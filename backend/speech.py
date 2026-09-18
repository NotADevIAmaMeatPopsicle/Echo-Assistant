"""Offline speech synthesis. Text and PCM stay in pipes and memory."""
import base64
import json
import os
from pathlib import Path
import subprocess
import time
from .speech_jobs import check_cancel

SCRIPT = r'''
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$config = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String([Console]::In.ReadToEnd().Trim())) | ConvertFrom-Json
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$memory = New-Object IO.MemoryStream
try {
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(48000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    $synth.Rate = [int]$config.rate
    if ($config.voice) { $synth.SelectVoice([string]$config.voice) }
    $synth.SetOutputToAudioStream($memory, $format)
    $synth.Speak([string]$config.text)
    [Console]::Out.Write([Convert]::ToBase64String($memory.ToArray()))
} finally { $synth.Dispose(); $memory.Dispose() }
'''


def available():
    return os.name == "nt" and (Path(os.environ.get("SystemRoot", "")) / "System32/WindowsPowerShell/v1.0/powershell.exe").is_file()


def voices():
    if not available(): return []
    script = r'''Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try { $names = @($synth.GetInstalledVoices() | Where-Object Enabled | ForEach-Object { $_.VoiceInfo.Name }); [Console]::Out.Write((ConvertTo-Json -Compress -InputObject $names)) } finally { $synth.Dispose() }'''
    executable = Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    try:
        result = subprocess.run([str(executable), '-NoProfile', '-NonInteractive', '-EncodedCommand',
            base64.b64encode(script.encode('utf-16-le')).decode('ascii')], stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        names = json.loads(result.stdout) if result.returncode == 0 else []
        return [name for name in names if isinstance(name, str)] if isinstance(names, list) else []
    except (OSError, ValueError, subprocess.TimeoutExpired): return []


def prepare(settings, *, cancel=None):
    check_cancel(cancel)
    if settings.tts_engine=='sapi':
        if not available(): raise RuntimeError('Local Windows speech engine unavailable')
        return {'engine':'sapi','status':'ready'}
    from .neural_speech import prepare as neural_prepare
    return neural_prepare(settings,cancel=cancel)


def synthesize(text: str, *, settings=None, cancel=None) -> bytes:
    return synthesize_checked(text, settings=settings,cancel=cancel)[0]


def synthesize_checked(text: str, *, settings=None, cancel=None):
    """Return PCM and timing without opening an audio device or writing recordings."""
    if not isinstance(text, str) or not 0 < len(text.strip()) <= 1200:
        raise ValueError("Spoken reply must contain 1–1200 characters")
    check_cancel(cancel)
    if settings is None:
        from .settings import speech_settings
        settings = speech_settings()
    if settings.tts_engine != 'sapi':
        from .neural_speech import synthesize as neural_synthesize
        return neural_synthesize(text,settings,cancel=cancel)
    if not available(): raise RuntimeError("Local Windows speech engine unavailable")
    started = time.monotonic()
    executable = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    command = [str(executable), "-NoProfile", "-NonInteractive", "-EncodedCommand",
        base64.b64encode(SCRIPT.encode("utf-16-le")).decode("ascii")]
    payload = base64.b64encode(json.dumps({'text':text,'voice':settings.tts_voice,'rate':settings.tts_rate}).encode('utf-8'))
    with subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                          creationflags=subprocess.CREATE_NO_WINDOW) as process:
        try:
            while True:
                check_cancel(cancel)
                if time.monotonic()-started>=25: raise TimeoutError('Local speech generation timed out')
                try:
                    output,_ = process.communicate(input=payload,timeout=.05)
                    check_cancel(cancel)
                    break
                except subprocess.TimeoutExpired: payload = None
        finally:
            if process.poll() is None: process.kill()
            process.communicate()
        if process.returncode: raise RuntimeError("Local speech synthesis failed")
    try: pcm = base64.b64decode(output, validate=True)
    except ValueError as error: raise RuntimeError("Invalid local speech output") from error
    if not pcm or len(pcm) % 2 or len(pcm) > 48000*2*90:
        raise RuntimeError("Local speech output outside bounds")
    elapsed = round((time.monotonic()-started)*1000)
    return pcm, {'ok':True, 'engine':'sapi', 'sample_rate':48000, 'seconds':round(len(pcm)/96000,3),
                 'generation_ms':elapsed, 'request_ms':elapsed, 'load_ms':0, 'first_chunk_ms':None}
