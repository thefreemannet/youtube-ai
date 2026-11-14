import json
import os
import shutil
import subprocess
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path('/opt/j3g-youtube-ai')
JOBS = ROOT / 'data/jobs'
job = sorted((p for p in JOBS.iterdir() if p.is_dir() and (p/'narration_xtts.wav').is_file()))[-1]
slides = job/'slides_v2'
slides.mkdir(exist_ok=True)
audio = job/'narration_xtts.wav'
fontpath = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
boldpath = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
W,H=720,1280

def fit(draw, text, rect, maximum=44, minimum=18, bold=False, color='#f8fafc', spacing=10):
    x,y,w,h=rect
    path=boldpath if bold else fontpath
    for size in range(maximum,minimum-1,-1):
        font=ImageFont.truetype(path,size)
        lines=[]
        for paragraph in text.split('\n'):
            line=''
            for word in paragraph.split():
                candidate=(line+' '+word).strip()
                if draw.textbbox((0,0),candidate,font=font)[2] <= w:
                    line=candidate
                else:
                    if line: lines.append(line)
                    line=word
            lines.append(line)
        block='\n'.join(lines)
        bounds=draw.multiline_textbbox((0,0),block,font=font,spacing=spacing,align='center')
        tw,th=bounds[2]-bounds[0],bounds[3]-bounds[1]
        if tw<=w and th<=h:
            tx=x+(w-tw)/2-bounds[0]
            ty=y+(h-th)/2-bounds[1]
            draw.multiline_text((tx,ty),block,font=font,fill=color,spacing=spacing,align='center')
            return size
    raise ValueError(f'Text cannot fit within {rect}: {text[:75]}')

def panel(d,xy,fill='#17263b',border='#3b82f6',radius=26):
    d.rounded_rectangle(xy,radius=radius,fill=fill,outline=border,width=3)

def new_slide(title):
    im=Image.new('RGB',(W,H),'#0b1221')
    d=ImageDraw.Draw(im)
    panel(d,(34,35,686,122),fill='#123b66',border='#123b66',radius=18)
    fit(d,'J3G  TECH  EXPLAINED',(58,52,604,54),30,22,True)
    fit(d,title,(44,155,632,118),49,28,True)
    d.line((60,1150,660,1150),fill='#334155',width=2)
    fit(d,'AI EDUCATIONAL VIDEO  |  BACnet',(60,1173,600,45),23,16,False,'#b6c6db')
    return im,d

files=[]
# 1 — Overview
im,d=new_slide('WHAT IS BACnet?')
d.ellipse((245,345,475,575),fill='#135a80',outline='#7dd3fc',width=5)
fit(d,'BACnet',(262,416,196,78),52,30,True)
panel(d,(65,655,655,1020))
fit(d,'Building Automation and Control Networks',(93,704,534,115),37,23,True)
fit(d,'An open standard that lets compatible building systems exchange information.',(99,854,522,128),32,21)
files.append(slides/'01_intro.png');im.save(files[-1])
# 2 — Network
im,d=new_slide('CONNECTED HVAC DEVICES')
coords=[(65,355,298,487),(422,355,655,487),(65,731,298,863),(422,731,655,863)]
for xy in coords:
    cx=(xy[0]+xy[2])/2;cy=(xy[1]+xy[3])/2
    d.line((360,610,cx,cy),fill='#38bdf8',width=7)
for xy,lab in zip(coords,['THERMOSTAT','AIR HANDLER','VAV BOX','CHILLER']):
    panel(d,xy,fill='#194b78',border='#7dd3fc')
    fit(d,lab,(xy[0]+14,xy[1]+20,xy[2]-xy[0]-28,xy[3]-xy[1]-40),31,19,True)
panel(d,(251,545,469,675),fill='#0b625c',border='#5eead4')
fit(d,'BACnet NETWORK',(267,555,186,110),30,20,True)
fit(d,'Compatible devices can exchange values such as temperatures, alarms, and equipment status.',(68,920,584,175),31,21)
files.append(slides/'02_devices.png');im.save(files[-1])
# 3 — Core concepts
im,d=new_slide('HOW BACnet SHARES DATA')
concepts=[('OBJECTS','Represent information, such as an Analog Input or Schedule.'),('PROPERTIES','Describe object values, status, and other characteristics.'),('SERVICES','Allow devices to read, write, and exchange supported information.')]
for i,(heading,body) in enumerate(concepts):
    top=325+i*262
    panel(d,(65,top,655,top+220))
    fit(d,heading,(99,top+22,522,58),36,24,True,'#7dd3fc')
    fit(d,body,(102,top+92,516,103),29,20)
files.append(slides/'03_concepts.png');im.save(files[-1])
# 4 — Caution
im,d=new_slide('IMPORTANT LIMITATIONS')
panel(d,(65,325,655,945),fill='#38202a',border='#fda4af')
fit(d,'BACnet is NOT a universal controller programming tool.',(110,360,500,182),38,24,True,'#ffe4e6')
d.line((120,580,600,580),fill='#fb7185',width=3)
fit(d,'Manufacturer-specific software may still be needed for setup, programming, and advanced functions.',(105,620,510,188),31,21)
fit(d,'Always check the device PICS document.',(113,836,494,75),28,19,True,'#fecdd3')
files.append(slides/'04_limitations.png');im.save(files[-1])
# 5 — Security
im,d=new_slide('BACnet & SECURITY')
panel(d,(65,326,655,672),fill='#16304e',border='#60a5fa')
fit(d,'BACnet/IP',(100,352,520,75),40,25,True)
fit(d,'Traditional BACnet/IP is not encrypted by default.',(110,457,500,145),32,22)
panel(d,(65,710,655,1057),fill='#123c3c',border='#5eead4')
fit(d,'BACnet/SC',(100,739,520,75),40,25,True)
fit(d,'BACnet Secure Connect uses TLS to protect communication.',(110,839,500,145),32,22)
files.append(slides/'05_security.png');im.save(files[-1])

getdur=['ffprobe','-v','error','-show_entries','format=duration','-of','default=noprint_wrappers=1:nokey=1']
duration=float(subprocess.check_output(getdur+[str(audio)],text=True).strip())
concat=job/'slides_v2.txt'
# Fine-grained illustrative pacing: actual scene boundaries are approximate.
weights=[0.18,0.24,0.20,0.20,0.18]
with concat.open('w',encoding='utf-8') as f:
    for picture,weight in zip(files,weights):
        f.write(f"file '{picture}'\n")
        f.write(f'duration {duration*weight:.4f}\n')
    f.write(f"file '{files[-1]}'\n")

new=job/'video_layout_v2.mp4'
subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','concat','-safe','0','-i',str(concat),'-i',str(audio),'-t',f'{duration:.3f}','-vf','fps=24,format=yuv420p','-c:v','libx264','-preset','fast','-c:a','aac','-b:a','128k','-movflags','+faststart',str(new)],check=True)
actual=float(subprocess.check_output(getdur+[str(new)],text=True).strip())
if abs(actual-duration)>0.5: raise RuntimeError(f'Video/audio mismatch: {actual:.3f} vs {duration:.3f}')
original=job/'video.mp4'
backup=job/'video_before_layout_fix.mp4'
if original.exists() and not backup.exists(): shutil.copy2(original,backup)
os.replace(new,original)
reportfile=job/'production_report.json'
report=json.loads(reportfile.read_text(encoding='utf-8')) if reportfile.exists() else {}
report.update({'duration_seconds':round(actual,2),'speaker':'Andrew Chipper','voice_engine':'xtts','visual_layout':'auto-fit-v2','video':str(original)})
reportfile.write_text(json.dumps(report,indent=2),encoding='utf-8')
print(f'LAYOUT TEST PASSED: {len(files)} slides, all text fits.')
print(f'VIDEO REBUILT: {actual:.2f}s; XTTS audio: {duration:.2f}s')
print('Dashboard video updated; old video backed up.')
