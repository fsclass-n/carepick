"""Synthesize narration sentence by sentence and write scene timing (timing.json).

Each sentence is generated separately so that a natural breath (GAP) can be inserted between
sentences. Voice processing: 80 Hz high-pass, gentle compression, slight 3 kHz presence.
If a scene's speech does not fit, the scene is regenerated slightly faster (max +8%).

usage: python tts.py WORK_DIR
"""
import asyncio
import json
import subprocess
import sys
import wave
from pathlib import Path

import edge_tts
import imageio_ffmpeg

import video_scenes as v

FF = imageio_ffmpeg.get_ffmpeg_exe()
WORK = Path(sys.argv[1])
OUT = WORK / 'tts'
OUT.mkdir(parents=True, exist_ok=True)
VOICE_FILTER = ('silenceremove=start_periods=1:start_silence=0.03:start_threshold=-45dB,areverse,'
                'silenceremove=start_periods=1:start_silence=0.03:start_threshold=-45dB,areverse,'
                'highpass=f=80,acompressor=threshold=-20dB:ratio=2.2:attack=12:release=180:makeup=1.5,'
                'equalizer=f=3000:t=q:w=1.2:g=1.5,aresample=48000')


def pct(rate):
    return int(rate.rstrip('%'))


async def synth(text, rate, mp3):
    await edge_tts.Communicate(text, v.VOICE, rate=rate).save(str(mp3))


def to_wav(mp3, wav):
    subprocess.run([FF, '-y', '-loglevel', 'error', '-i', str(mp3), '-af', VOICE_FILTER,
                    '-ac', '2', '-ar', '48000', '-c:a', 'pcm_s16le', str(wav)], check=True)
    with wave.open(str(wav)) as w:
        return w.getnframes() / w.getframerate()


def build(scene, rate):
    lines, t = [], v.LEAD
    for k, line in enumerate(scene['lines']):
        mp3, wav = OUT / f"{scene['id']}_{k}.mp3", OUT / f"{scene['id']}_{k}.wav"
        for attempt in range(4):
            try:
                asyncio.run(synth(line['say'], rate, mp3))
                break
            except Exception:
                if attempt == 3:
                    raise
        d = to_wav(mp3, wav)
        lines.append({**line, 't': round(t, 3), 'd': round(d, 3), 'wav': wav.name})
        t += d + v.GAP
    return lines, t - v.GAP


def main():
    report = []
    for sc in v.timeline():
        rate = v.RATE
        while True:
            lines, end = build(sc, rate)
            if end <= sc['dur'] - v.TAIL or pct(rate) >= 8:
                break
            rate = f'{pct(rate) + 3:+d}%'
        sc['lines'], sc['speech_end'], sc['rate'] = lines, round(end, 3), rate
        fits = end <= sc['dur'] - v.TAIL
        report.append(fits)
        print(f"{sc['id']}  {sc['start']:6.1f}s  dur {sc['dur']:4.1f}  speech {end:5.2f}  rate {rate:>4}  {'OK' if fits else 'TOO LONG'}")
    (WORK / 'timing.json').write_text(json.dumps(v.SCENES, ensure_ascii=False, indent=1), encoding='utf-8')
    speech = sum(sum(l['d'] for l in s['lines']) for s in v.SCENES)
    print(f'speech total {speech:.1f}s / {v.TOTAL}s · scenes too long: {report.count(False)}')
    sys.exit(0 if all(report) else 1)


if __name__ == '__main__':
    main()
